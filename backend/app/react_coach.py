"""Unified Safety-Gated ReAct Coach Engine (ADR-0001 & ADR-0003).

Consolidates RunSense's 7 coaching tools behind an immutable, monotonically
escalating `AgentSecurityEnvelope` so neither prompt injection nor probabilistic
LLM tool arguments can ever downgrade medical triage urgency or re-enable
blocked running recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import json
import re
from typing import Any, Callable, Literal, Mapping, Sequence
import uuid

from sqlalchemy import Connection, text

from app.garmin_ingest import get_latest_wellness
from app.multimedia_education import HealthMediaRequest, get_multimedia_education_service
from app.plan_scenario import _max_urgency, urgency_from_severity_band
from app.safety_triage import TriageUrgency, assess_safety_triage_text
from app.weather_pace import speed_loss_pct_relative_to_normal

REACT_TOOL_NAMES: tuple[str, ...] = (
    "observe_athlete_status",
    "get_wellness_baseline",
    "analyze_fit_workout",
    "compute_heat_pace",
    "evaluate_training_plan",
    "retrieve_evidence",
    "generate_health_media",
)
AVAILABLE_TOOLS: tuple[str, ...] = REACT_TOOL_NAMES

_ENGLISH_EMERGENCY = (
    "chest pain",
    "shortness of breath",
    "difficulty breathing",
    "uncontrolled bleeding",
    "fainting",
    "collapsed",
    "heat stroke",
)
_ENGLISH_CLINICIAN = (
    "cannot bear weight",
    "unable to bear weight",
    "visible deformity",
    "new numbness",
    "bone pain",
    "stress fracture",
)

_MEDIA_KEYWORDS = (
    "圖",
    "影片",
    "視頻",
    "海報",
    "衛教圖",
    "視覺",
    "image",
    "png",
    "svg",
    "video",
    "mp4",
    "infographic",
)
_WELLNESS_KEYWORDS = (
    "睡眠",
    "hrv",
    "靜息心率",
    "休息心率",
    "body battery",
    "壓力",
    "恢復",
    "手環",
    "garmin",
    "sleep",
    "wellness",
    "vo2",
)
_FIT_KEYWORDS = (
    "fit",
    "配速漂移",
    "分段",
    "分圈",
    "心率區間",
    "步頻",
    "lap",
    "telemetry",
    "workout analysis",
)
_HEAT_KEYWORDS = ("天氣", "氣溫", "高溫", "熱", "濕度", "配速", "補償", "°c", "weather", "heat", "pace")
_PLAN_KEYWORDS = ("課表", "今天", "跑什麼", "分鐘", "訓練", "推薦", "plan", "workout", "run")
_EVIDENCE_KEYWORDS = ("指引", "文獻", "科學", "原則", "依據", "為什麼", "痛", "傷", "緊", "痠", "evidence", "injury")


@dataclass(frozen=True)
class AgentSecurityEnvelope:
    """Immutable-direction clinical gate locked before ReAct tool execution."""

    triage_urgency: TriageUrgency | None = None
    running_allowed: bool = True
    reason_codes: tuple[str, ...] = ()
    locked: bool = True

    @classmethod
    def from_inputs(
        cls,
        *,
        message: str = "",
        recorded_urgency: TriageUrgency | None = None,
        severity_band: str | None = None,
        body_part: str | None = None,
        free_text: str | None = None,
    ) -> "AgentSecurityEnvelope":
        urgency: TriageUrgency | None = recorded_urgency
        reasons: list[str] = []

        if recorded_urgency is not None:
            reasons.append(f"RECORDED:{recorded_urgency.value}")

        band_urgency = urgency_from_severity_band(severity_band)
        if band_urgency is not None:
            urgency = _max_urgency(urgency, band_urgency)
            reasons.append(f"SEVERITY_BAND:{str(severity_band).upper()}")

        for source_name, txt in (("MESSAGE", message), ("FREE_TEXT", free_text or "")):
            cleaned = str(txt or "").strip()
            if not cleaned:
                continue
            decision = assess_safety_triage_text(
                severity_band=None, body_part=body_part, message=cleaned
            )
            if decision is not None:
                urgency = _max_urgency(urgency, decision.urgency)
                for rule_id in decision.matched_rule_ids:
                    if rule_id not in reasons:
                        reasons.append(rule_id)
                if not decision.matched_rule_ids and f"{source_name}_SIGNAL" not in reasons:
                    reasons.append(f"{source_name}_SIGNAL")
            lowered = cleaned.lower()
            if any(phrase in lowered for phrase in _ENGLISH_EMERGENCY):
                urgency = _max_urgency(urgency, TriageUrgency.EMERGENCY)
                reasons.append("ENGLISH_RED_FLAG_EMERGENCY")
            elif any(phrase in lowered for phrase in _ENGLISH_CLINICIAN):
                urgency = _max_urgency(urgency, TriageUrgency.PROMPT_CLINICIAN)
                reasons.append("ENGLISH_PROMPT_CLINICIAN")

        blocked = urgency in {TriageUrgency.EMERGENCY, TriageUrgency.PROMPT_CLINICIAN}
        return cls(
            triage_urgency=urgency,
            running_allowed=not blocked,
            reason_codes=tuple(reasons),
            locked=True,
        )

    def escalate(
        self,
        new_urgency: TriageUrgency | None,
        reason: str | None = None,
    ) -> "AgentSecurityEnvelope":
        """Monotonically escalate urgency; returns a new immutable envelope."""
        merged = _max_urgency(self.triage_urgency, new_urgency)
        rank = {
            TriageUrgency.SELF_CARE_NEXT_STEP: 1,
            TriageUrgency.PROMPT_CLINICIAN: 2,
            TriageUrgency.EMERGENCY: 3,
        }
        cur_rank = rank[self.triage_urgency] if self.triage_urgency else 0
        merged_rank = rank[merged] if merged is not None else 0
        if merged_rank > cur_rank and merged is not None:
            next_reasons = (
                (*self.reason_codes, reason)
                if reason and reason not in self.reason_codes
                else self.reason_codes
            )
            blocked = merged in {TriageUrgency.EMERGENCY, TriageUrgency.PROMPT_CLINICIAN}
            return AgentSecurityEnvelope(
                triage_urgency=merged,
                running_allowed=self.running_allowed and not blocked,
                reason_codes=next_reasons,
                locked=True,
            )
        return self

    def stop_running_banner(self) -> str:
        """Return the mandatory non-running safety notice matching triage urgency."""
        return (
            "【安全分流優先提醒：立即停止跑步並尋求緊急醫療協助】"
            if self.triage_urgency is TriageUrgency.EMERGENCY
            else "【安全分流優先提醒：建議暫停跑步，並儘快由合格醫療專業人員評估】"
        )

    def enforce_on_reply(self, reply_text: str) -> str:
        """Guarantee blocked running replies carry explicit stop-running guidance."""
        if self.running_allowed:
            return reply_text
        stop_markers = ("停止跑步", "暫停跑步", "請勿跑步", "不要跑", "就醫", "stop running", "clinician", "medical")
        lowered = reply_text.lower()
        if any(m in lowered for m in stop_markers):
            return reply_text
        return f"{self.stop_running_banner()}\n\n{reply_text}".strip()


@dataclass(frozen=True)
class UnifiedReactStep:
    step: int
    thought: str
    action: str
    observation: str


@dataclass(frozen=True)
class UnifiedReactOutcome:
    reply_text: str
    answer_source: Literal["MODEL", "UNAVAILABLE", "NOT_CONFIGURED"]
    triage_urgency: str | None
    running_allowed: bool
    trace: tuple[UnifiedReactStep, ...]
    rag_citations: list[dict[str, str]] = field(default_factory=list)
    media_asset: dict[str, Any] | None = None
    grounding_notes: list[str] = field(default_factory=list)


def _detect_requested_media_format(question: str) -> Literal["png", "mp4", "svg"] | None:
    q = question.lower()
    if any(k in q for k in ("影片", "視頻", "video", "mp4")):
        return "mp4"
    if "svg" in q:
        return "svg"
    if any(k in q for k in _MEDIA_KEYWORDS):
        return "png"
    return None


def _run_tool(
    action: str,
    *,
    question: str,
    envelope: AgentSecurityEnvelope,
    context: Mapping[str, Any],
    athlete_id: uuid.UUID | None,
    conn: Connection | None,
    local_date: date | None,
    tool_overrides: Mapping[str, Callable[..., Any]] | None,
) -> tuple[str, list[str], dict[str, Any] | None]:
    """Execute one named tool under `envelope` and return (obs, grounding_lines, media_asset)."""
    if tool_overrides and action in tool_overrides:
        res = tool_overrides[action](question=question, context=context, envelope=envelope)
        if isinstance(res, dict) and "observation" in res:
            return str(res["observation"]), [str(res["observation"])], res.get("media_asset")
        return str(res), [str(res)], None

    if action == "observe_athlete_status":
        acute = context.get("acute_load")
        chronic = context.get("chronic_load")
        ratio = context.get("load_ratio")
        obs_days = context.get("observation_days", 0)
        inj = context.get("body_part") or context.get("severity_band")
        obs = (
            f"近期觀測 {obs_days} 天；7天負荷 {acute} AU，28天基準 {chronic} AU，ACWR {ratio}"
            + (f"；身體回報：{context.get('body_part') or ''}({context.get('severity_band') or ''})" if inj else "；無主動傷痛回報")
        )
        return obs, [obs], None

    if action == "get_wellness_baseline":
        wellness = context.get("wellness")
        if wellness is None and conn is not None and athlete_id is not None:
            summary = get_latest_wellness(conn, athlete_id, on_date=local_date)
            wellness = summary.to_dict() if summary is not None else None
        if isinstance(wellness, Mapping):
            obs = (
                f"Garmin 恢復指標：RHR {wellness.get('resting_hr_bpm')} bpm"
                f"（基線差 {wellness.get('resting_hr_delta')}）、"
                f"HRV {wellness.get('hrv_ms')} ms（{wellness.get('hrv_status')}）、"
                f"睡眠 {wellness.get('sleep_hours')} 小時、Body Battery {wellness.get('body_battery_recent')}。"
            )
            return obs, [obs], None
        return "尚無 Garmin 每日生理恢復紀錄（HRV / 睡眠 / 靜息心率）。", [], None

    if action == "analyze_fit_workout":
        latest_fit = context.get("latest_fit_analysis")
        if isinstance(latest_fit, Mapping) and latest_fit.get("metrics") is not None:
            m = dict(latest_fit.get("metrics") or {})
            sig = latest_fit.get("signature") or "workout"
            obs = (
                f"最新 .fit 訓練分析（{sig}）：平均心率 {m.get('avg_hr')} bpm、"
                f"心率漂移 {m.get('cardiac_drift_pct')}%、平均步頻 {m.get('avg_cadence_spm')} spm。"
            )
            return obs, [obs], None
        if conn is not None and athlete_id is not None:
            row = conn.execute(
                text(
                    "SELECT w.signature, w.metrics FROM workout_analyses w "
                    "JOIN completed_activities a ON a.id = w.activity_id "
                    "WHERE w.athlete_id = :a AND a.deleted_at IS NULL "
                    "ORDER BY a.local_training_date DESC, w.updated_at DESC LIMIT 1"
                ),
                {"a": athlete_id},
            ).first()
            if row is not None:
                m = dict(row.metrics or {})
                obs = (
                    f"最新 .fit 訓練分析（{row.signature}）：平均心率 {m.get('avg_hr')} bpm、"
                    f"心率漂移 {m.get('cardiac_drift_pct')}%、平均步頻 {m.get('avg_cadence_spm')} spm。"
                )
                return obs, [obs], None
        recent = (context.get("recent_training") or {}) if isinstance(context.get("recent_training"), Mapping) else {}
        if recent:
            obs = (
                f"近 28 天已完成 {recent.get('activity_count', 0)} 次活動，"
                f"總距離 {recent.get('total_distance_km', 0)} km，平均心率 {recent.get('average_heart_rate_bpm')} bpm。"
            )
            return obs, [obs], None
        return "近期尚無已解析的 .fit 分段遙測紀錄。", [], None

    if action == "compute_heat_pace":
        temp = context.get("temperature")
        hum = context.get("humidity")
        ref_c = context.get("climate_reference_c")
        sex = context.get("sex")
        if temp is not None and ref_c is not None:
            loss = speed_loss_pct_relative_to_normal(float(temp), float(ref_c), sex)
            obs = f"目前氣溫 {temp}°C、濕度 {hum}%（常態基準 {ref_c}°C），El Helou 估算相對速度影響約 {loss:.2f}%。"
            return obs, [obs], None
        if temp is not None:
            obs = f"目前氣溫 {temp}°C、濕度 {hum}%；缺乏城市常態基準可對照，建議以心率與體感為主。"
            return obs, [obs], None
        return "目前缺少即時氣溫資料，無法計算天候補償。", [], None

    if action == "evaluate_training_plan":
        if not envelope.running_allowed:
            obs = (
                f"安全分流已鎖定（{envelope.triage_urgency.value if envelope.triage_urgency else 'BLOCKED'}）："
                "僅允許休息與尋求醫療評估（REST_AND_SEEK_CARE），模型不得推薦跑步課表。"
            )
            return obs, [obs], None
        plan = context.get("plan_evaluation")
        if isinstance(plan, Mapping) and plan.get("candidates"):
            top = plan["candidates"][0]
            obs = (
                f"受限候選課表首選：{top.get('workout_type')}（{top.get('duration_minutes')} 分鐘 / "
                f"{top.get('distance_km')} km），排序器={plan.get('ranker_version')}，棄權={plan.get('abstained')}。"
            )
            return obs, [obs], None
        return "今日課表遵循確定性安全邊界，優先維持可負荷的有氧與恢復。", [], None

    if action == "retrieve_evidence":
        passages = context.get("rag_passages") or []
        if passages:
            titles = "、".join(f"《{p.get('title')}》({p.get('publisher')})" for p in passages[:3])
            obs = f"已檢索 {len(passages)} 筆經審核運動醫學指引：{titles}。"
            return obs, [obs], None
        return "知識庫無額外吻合段落，維持一般非診斷運動安全衛教邊界。", [], None

    if action == "generate_health_media":
        fmt = _detect_requested_media_format(question) or "png"
        passages = context.get("rag_passages") or []
        citations = [
            f"{p.get('publisher', 'Guideline')}: {p.get('title', 'Sports Medicine Guidance')}"
            for p in passages[:3]
        ] or ["RunSense Reviewed Safety Triage Rules"]
        steps = [
            "確認目前安全分流與身體症狀變化",
            "依負荷比與高溫環境調整今日節奏或改為休息",
            "僅於無負重骨痛或紅旗警示時漸進恢復",
        ]
        summary = (
            "目前安全分流已暫停跑步建議，請優先休息並就醫評估。"
            if not envelope.running_allowed
            else "整合近期訓練負荷、生理恢復與環境溫度提供安全運動衛教。"
        )
        req = HealthMediaRequest(
            topic=f"RunSense 個人化衛教：{context.get('body_part') or '科學化跑步管理'}",
            body_part=context.get("body_part"),
            triage_urgency=envelope.triage_urgency,
            running_allowed=envelope.running_allowed,
            guidance_summary=summary,
            next_steps=steps,
            citations=citations,
            media_format=fmt,
            athlete_context={
                "load_ratio": context.get("load_ratio"),
                "temperature": context.get("temperature"),
            },
        )
        media_svc = get_multimedia_education_service()
        artifact = media_svc.generate(req)
        if athlete_id is not None and callable(getattr(media_svc, "store_asset", None)):
            media_svc.store_asset(athlete_id, artifact)
        asset_dict = {
            "asset_id": artifact.asset_id,
            "media_format": artifact.media_format,
            "mime_type": artifact.mime_type,
            "file_size_bytes": artifact.file_size_bytes,
            "generator_mode": artifact.generator_mode,
            "triage_urgency": artifact.triage_urgency,
            "download_url": f"/guidance/media/{artifact.asset_id}",
        }
        obs = (
            f"已產生衛教媒體檔案（{artifact.media_format.upper()}，模式 {artifact.generator_mode}，"
            f"{artifact.file_size_bytes} bytes，asset_id={artifact.asset_id}）。"
        )
        return obs, [obs], asset_dict

    return f"未知工具 {action}", [], None


def _select_tool_plan(question: str, envelope: AgentSecurityEnvelope) -> list[str]:
    """Deterministic multi-step tool order tuned to question intent + safety."""
    q = question.lower()
    chosen: list[str] = ["observe_athlete_status"]
    if any(k in q for k in _WELLNESS_KEYWORDS):
        chosen.append("get_wellness_baseline")
    if any(k in q for k in _FIT_KEYWORDS):
        chosen.append("analyze_fit_workout")
    if any(k in q for k in _HEAT_KEYWORDS):
        chosen.append("compute_heat_pace")
    if any(k in q for k in _PLAN_KEYWORDS) or not envelope.running_allowed:
        chosen.append("evaluate_training_plan")
    if any(k in q for k in _EVIDENCE_KEYWORDS) or len(chosen) < 2:
        chosen.append("retrieve_evidence")
    if _detect_requested_media_format(question) is not None:
        chosen.append("generate_health_media")
    # Deduplicate preserving order within max_steps=4
    deduped: list[str] = []
    for t in chosen:
        if t not in deduped:
            deduped.append(t)
    return deduped[:4]


def run_unified_react_coach(
    *,
    question: str,
    surface_profile: Literal["private_guidance", "team_direct_chat"] = "private_guidance",
    envelope: AgentSecurityEnvelope | None = None,
    context: Mapping[str, Any] | None = None,
    messages: Sequence[dict[str, str]] | None = None,
    athlete_id: uuid.UUID | None = None,
    conn: Connection | None = None,
    local_date: date | None = None,
    room_kind: str = "private",
    is_coach_user: bool = False,
    has_consent: bool = True,
    tool_overrides: Mapping[str, Callable[..., Any]] | None = None,
    llm_complete_fn: Callable[[list[dict[str, str]], dict[str, Any]], tuple[str, str]] | None = None,
    max_steps: int = 4,
) -> UnifiedReactOutcome:
    """Execute the unified 7-tool ReAct coaching loop with immutable safety bounds."""
    env = envelope or AgentSecurityEnvelope.from_inputs(
        message=question,
        severity_band=(context or {}).get("severity_band"),
        body_part=(context or {}).get("body_part"),
    )
    ctx = dict(context or {})

    if surface_profile == "team_direct_chat":
        if room_kind == "team":
            trace = (
                UnifiedReactStep(
                    step=1,
                    thought="公開團隊頻道禁止揭露個人生理負荷與傷痛資料。",
                    action="privacy_guard",
                    observation="已阻擋團隊頻道個人遙測查詢。",
                ),
            )
            return UnifiedReactOutcome(
                reply_text=env.enforce_on_reply(
                    "群組裡不公開任何人的負荷、傷痛或個人課表建議，請到一對一聊天室或 AI 健康教練查看。"
                ),
                answer_source="NOT_CONFIGURED",
                triage_urgency=env.triage_urgency.value if env.triage_urgency else None,
                running_allowed=env.running_allowed,
                trace=trace,
            )
        if is_coach_user and not has_consent:
            trace = (
                UnifiedReactStep(
                    step=1,
                    thought="教練檢視選手數據與課表前必須驗證 training_load 授權範圍。",
                    action="consent_check",
                    observation="選手未授權 training_load 同意範圍。",
                ),
            )
            return UnifiedReactOutcome(
                reply_text=env.enforce_on_reply("這位選手尚未授權教練查看訓練負荷與個人建議。"),
                answer_source="NOT_CONFIGURED",
                triage_urgency=env.triage_urgency.value if env.triage_urgency else None,
                running_allowed=env.running_allowed,
                trace=trace,
            )

    planned_tools = _select_tool_plan(question, env)[: max(1, min(4, max_steps))]
    trace_steps: list[UnifiedReactStep] = []
    grounding_notes: list[str] = []
    media_asset: dict[str, Any] | None = None

    for idx, tool_name in enumerate(planned_tools, start=1):
        obs, g_lines, asset = _run_tool(
            tool_name,
            question=question,
            envelope=env,
            context=ctx,
            athlete_id=athlete_id,
            conn=conn,
            local_date=local_date,
            tool_overrides=tool_overrides,
        )
        grounding_notes.extend(g_lines)
        if asset is not None:
            media_asset = asset
        trace_steps.append(
            UnifiedReactStep(
                step=idx,
                thought=f"執行工具 `{tool_name}` 檢查跑者事實與安全邊界。",
                action=tool_name,
                observation=obs,
            )
        )

    rag_passages = list(ctx.get("rag_passages") or [])[:3]
    rag_citations = [
        {
            "title": str(p.get("title") or ""),
            "publisher": str(p.get("publisher") or ""),
            "source_url": str(p.get("source_url") or ""),
        }
        for p in rag_passages
        if isinstance(p, Mapping)
    ]

    enriched_ctx = dict(ctx)
    enriched_ctx["triage_urgency"] = (
        env.triage_urgency.value if env.triage_urgency else ctx.get("triage_urgency")
    )
    enriched_ctx["triage_running_allowed"] = env.running_allowed
    if grounding_notes:
        enriched_ctx["react_observations"] = "\n".join(grounding_notes)

    reply_text = ""
    answer_source: Literal["MODEL", "UNAVAILABLE", "NOT_CONFIGURED"] = "NOT_CONFIGURED"
    if llm_complete_fn is not None:
        msg_list = list(messages or [{"role": "user", "content": question}])
        reply_text, answer_source = llm_complete_fn(msg_list, enriched_ctx)

    if not reply_text.strip():
        obs_summary = "\n".join(f"- {s.observation}" for s in trace_steps)
        reply_text = (
            f"【RunSense 安全邊界整合評估】\n{obs_summary}\n\n"
            "*本說明僅供運動生理教育參考，不取代專業醫療診斷或治療。*"
        )
        if answer_source != "UNAVAILABLE":
            answer_source = "NOT_CONFIGURED"

    final_reply = env.enforce_on_reply(reply_text)
    return UnifiedReactOutcome(
        reply_text=final_reply,
        answer_source=answer_source,
        triage_urgency=env.triage_urgency.value if env.triage_urgency else None,
        running_allowed=env.running_allowed,
        trace=tuple(trace_steps),
        rag_citations=rag_citations,
        media_asset=media_asset,
        grounding_notes=grounding_notes,
    )
