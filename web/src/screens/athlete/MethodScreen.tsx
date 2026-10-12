import { useEffect, useState } from "react";
import { Badge, Button, Card, InfoTip, Notice } from "../../components/ui.tsx";
import { DataQualityBadge } from "../../components/domain.tsx";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import { useAuth } from "../../state/AuthContext.tsx";
import { useLocale } from "../../state/LocaleContext.tsx";
import { apiConfigured, getPlanModelReport } from "../../data/apiClient.ts";
import type { PlanModelReportWire } from "../../data/apiClient.ts";
import {
  ACUTE_WINDOW_DAYS,
  ALGORITHM_VERSION,
  CHRONIC_WINDOW_DAYS,
  MIN_OBSERVATION_DAYS,
} from "../../lib/trainingLoad.ts";

const COPY = {
  "zh-TW": {
    intro:
      "這一頁把每個畫面上的數字攤開來看：它用了哪個演算法、什麼門檻、以及背後的實證來源。所有推論都在後端完成，個資與 GPS 不會送往外部生成式服務。",
    demoOnly: "目前為展示模式，未連線後端，以下顯示的是各演算法的設計說明。",
    planTitle: "智慧課表決策（規則式排序）",
    planDesc:
      "候選課表來自審核過的固定模板（休息／恢復／輕鬆／穩定），排序器只能『重新排序』，不能新增或改動距離、時間、強度（ADR 0002）。",
    planLoading: "正在載入今日課表決策…",
    planErr: "暫時無法載入課表決策。",
    reason: "排序理由",
    confidence: "決策信心",
    coverage: "特徵涵蓋度",
    inputs: "本次輸入",
    ratio: "短長期負荷比",
    obsDays: "觀測天數",
    temp: "氣溫",
    weatherState: "天氣資料狀態",
    triage: "安全分流",
    candidates: "候選課表排序（分數越高越優先）",
    abstain: "資料不足，排序器保守回退為『由輕到重』，且不輸出信心值。",
    modelTitle: "課表排序模型評估（離線、防資料洩漏）",
    modelDesc:
      "後端 backend/ml 內建一套離線評估：時間向前、以運動員分組、留間隔的切分，回報校準度、涵蓋率與分群結果。生產環境仍使用規則式排序，任何學習模型都不會被自動啟用（ADR 0002）。",
    modelLoading: "正在執行離線評估…",
    modelErr: "暫時無法取得模型評估報告。",
    yourHistory: "你的訓練歷史（真實資料）",
    featTitle: "用你的資料做預測（模型 vs 你實際做的）",
    featMatchRate: "首選命中率",
    featPredicted: "模型預測",
    featActual: "你實際做的",
    featMatched: "命中",
    activities: "完成訓練數",
    spanDays: "歷史涵蓋天數",
    sinceLast: "距上次訓練",
    evalOn: "評估資料列數",
    metrics: "基準模型（邏輯迴歸）指標",
    ece: "ECE 校準誤差（越低越好）",
    brier: "Brier 分數（越低越好）",
    mrr: "MRR 平均倒數排名（越高越好）",
    tcu: "Top-choice 效用（越高越好）",
    absCov: "自我保留涵蓋率",
    winner: "是否採用學習模型",
    no: "否 — 生產環境維持規則式",
    loadTitle: "體能負荷演算法（ACWR）",
    loadDesc:
      "急性負荷＝近 7 天訓練量；慢性負荷＝近 28 天換算每週基準；比值＝急性 ÷ 慢性。這是多個輸入之一，不是單一風險燈號。",
    threshold: "門檻",
    thresholdBody: `28 天內少於 ${MIN_OBSERVATION_DAYS} 天有紀錄時，不顯示負荷比，資料品質標記為「不足」，並改給保守的輕鬆課表。`,
    current: "目前數值",
    acute: "急性負荷（7 天）",
    chronic: "慢性負荷（28 天）",
    quality: "資料品質",
    weatherTitle: "天候等效配速（El Helou 曲線）",
    weatherDesc:
      "以 El Helou 等人 (2012) 的溫度—速度曲線為基礎，改用競賽型（P1）分層、以固定傍晚參考時刻的氣候常態溫度為基準相減，超出實測範圍時用邊界切線外插（不再往外套二次曲線）。詳見專案 CONTEXT.md。",
    wNow: "目前速度損失",
    wVsNormal: "相對常態（重新置中）",
    wClimateRef: "傍晚參考溫度",
    wUnavailable: "目前沒有可用的天氣資料。",
    triageTitle: "安全分流規則（固定規則，AI 不得調整）",
    triageDesc:
      "身體回報送出後，先由固定規則決定緊急度與是否可以跑步，之後才附上有來源的衛教資訊。AI 只能依據附上的資料說明，不能調低緊急度，也不能放行跑步。",
    tUrgency: "緊急度",
    tTrigger: "觸發條件",
    tRun: "可否跑步",
    tEmergency: "胸痛／呼吸困難、意識混亂、運動中倒下、嚴重熱傷害",
    tPrompt: "嚴重程度分級、明顯外傷、局部骨頭壓痛且負重更痛",
    tSelfCare: "輕度／中度不適，無上述警訊",
    tNo: "否",
    tYesCaution: "可，但降低強度",
    evidenceTitle: "實證資料庫",
    evidenceBody:
      "後端維護一份審核過的運動醫學短文圖譜（sports-medicine-v1），涵蓋小腿、膝、阿基里斯腱、足底、脛前、下背、髖／臀等常見部位，含中英雙語關鍵字與來源連結（AAOS OrthoInfo、ACSM 等）。傷害回報時以部位檢索，找不到對應時退回一般負荷管理短文，因此引用來源永遠不會是空的。",
    versionsTitle: "版本註冊表",
    vRanker: "課表排序器",
    vLoad: "體能負荷演算法",
    vGuidance: "課表建議規則",
    vTriage: "安全分流規則",
    vEvidence: "實證語料版本",
  },
  en: {
    intro:
      "This page opens up every number on screen: which algorithm produced it, what threshold gates it, and the evidence behind it. All inference runs on the backend; personal data and GPS never reach an external generative service.",
    demoOnly: "Demo mode — no backend connected. The sections below describe each algorithm's design.",
    planTitle: "Training plan decision (rule-based ranking)",
    planDesc:
      "Candidates come from reviewed fixed templates (rest / recovery / easy / steady). The ranker may only reorder them — never add one or change distance, duration, or intensity (ADR 0002).",
    planLoading: "Loading today's plan decision…",
    planErr: "Plan decision unavailable right now.",
    reason: "Ranking reason",
    confidence: "Decision confidence",
    coverage: "Feature coverage",
    inputs: "Inputs this run",
    ratio: "Acute/chronic ratio",
    obsDays: "Observation days",
    temp: "Temperature",
    weatherState: "Weather data state",
    triage: "Safety triage",
    candidates: "Ranked candidates (higher score = preferred)",
    abstain: "Not enough data — the ranker fell back to gentlest-first and withholds a confidence value.",
    modelTitle: "Plan-ranker model evaluation (offline, leakage-safe)",
    modelDesc:
      "backend/ml ships an offline benchmark: forward-time, athlete-grouped, gapped splits reporting calibration, coverage, and subgroup results. Production stays deterministic; no learned model is auto-enabled (ADR 0002).",
    modelLoading: "Running the offline evaluation…",
    modelErr: "Model evaluation report unavailable right now.",
    yourHistory: "Your training history (real data)",
    featTitle: "Predicted on your data (model vs. what you actually did)",
    featMatchRate: "Top-choice match rate",
    featPredicted: "Model predicted",
    featActual: "You actually did",
    featMatched: "Match",
    activities: "Completed activities",
    spanDays: "History span (days)",
    sinceLast: "Days since last activity",
    evalOn: "Evaluation rows",
    metrics: "Baseline model (logistic regression) metrics",
    ece: "ECE calibration error (lower is better)",
    brier: "Brier score (lower is better)",
    mrr: "MRR mean reciprocal rank (higher is better)",
    tcu: "Top-choice utility (higher is better)",
    absCov: "Abstention coverage",
    winner: "Learned model adopted?",
    no: "No — production stays rule-based",
    loadTitle: "Training-load algorithm (ACWR)",
    loadDesc:
      "Acute load = last 7 days of session load; chronic load = 28-day weekly baseline; ratio = acute ÷ chronic. One input among several, not a single risk light.",
    threshold: "Threshold",
    thresholdBody: `With fewer than ${MIN_OBSERVATION_DAYS} recorded days in the last 28, the ratio is hidden, data quality is marked "insufficient", and a conservative easy workout is given instead.`,
    current: "Current values",
    acute: "Acute load (7d)",
    chronic: "Chronic load (28d)",
    quality: "Data quality",
    weatherTitle: "Weather-equivalent pace (El Helou curve)",
    weatherDesc:
      "Based on El Helou et al. (2012) temperature–speed curve, re-fitted to the competitive (P1) tier, compared against the climate-normal temperature at a fixed early-evening reference hour, with boundary-tangent extrapolation past the measured range. See the project CONTEXT.md.",
    wNow: "Current speed loss",
    wVsNormal: "Relative to normal (re-centred)",
    wClimateRef: "Early-evening reference temp",
    wUnavailable: "No weather data available right now.",
    triageTitle: "Safety-triage rules (fixed rules the AI cannot change)",
    triageDesc:
      "After a body-status report, fixed rules decide urgency and whether running is allowed; only then is cited educational content attached. The AI may only explain from the evidence supplied — it cannot lower urgency or clear running.",
    tUrgency: "Urgency",
    tTrigger: "Trigger",
    tRun: "Running",
    tEmergency: "Chest pain / breathing difficulty, confusion, collapse in exercise, severe heat illness",
    tPrompt: "Severe severity band, visible deformity, focal bone pain worse with weight-bearing",
    tSelfCare: "Mild / moderate discomfort with none of the above",
    tNo: "No",
    tYesCaution: "Yes, at reduced intensity",
    evidenceTitle: "Evidence library",
    evidenceBody:
      "The backend keeps a reviewed sports-medicine passage graph (sports-medicine-v1) covering calf, knee, Achilles, plantar, shin, lower back, hip/glute and more, with bilingual keywords and source links (AAOS OrthoInfo, ACSM, etc.). Injury reports retrieve by body part; when nothing matches it falls back to general load-management passages, so a citation is never empty.",
    versionsTitle: "Version registry",
    vRanker: "Plan ranker",
    vLoad: "Training-load algorithm",
    vGuidance: "Plan guidance rules",
    vTriage: "Safety-triage rules",
    vEvidence: "Evidence corpus version",
  },
} as const;

const PLAN_TYPE_LABEL: Record<string, { "zh-TW": string; en: string }> = {
  REST_DAY: { "zh-TW": "休息日", en: "Rest day" },
  REST_AND_SEEK_CARE: { "zh-TW": "休息並尋求評估", en: "Rest and seek assessment" },
  RECOVERY_RUN: { "zh-TW": "恢復跑", en: "Recovery run" },
  EASY_RUN: { "zh-TW": "輕鬆跑", en: "Easy run" },
  STEADY_RUN: { "zh-TW": "穩定跑", en: "Steady run" },
};

const REASON_LABEL: Record<string, { "zh-TW": string; en: string }> = {
  LOAD_ELEVATED_FAVOR_RECOVERY: {
    "zh-TW": "近期負荷偏高，偏好較輕的訓練",
    en: "Recent load is elevated — favouring lighter work",
  },
  LOAD_REDUCED_ADD_STIMULUS: {
    "zh-TW": "近期負荷偏低，可加入適度刺激",
    en: "Recent load is low — room for a moderate stimulus",
  },
  STEADY_STATE: { "zh-TW": "負荷穩定，維持一般有氧訓練", en: "Load is steady — hold general aerobic work" },
  SELF_CARE_LIMIT_INTENSITY: {
    "zh-TW": "自我照護分流，限制強度",
    en: "Self-care triage — intensity is capped",
  },
  TRIAGE_BLOCKED: { "zh-TW": "安全分流暫不建議跑步", en: "Safety triage is holding running" },
  COLD_START_ABSTAIN: {
    "zh-TW": "觀測資料不足，改用保守排序",
    en: "Not enough observation history — using a conservative order",
  },
};

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}
function num(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined ? "—" : value.toFixed(digits);
}

export function MethodScreen() {
  const { locale } = useLocale();
  const c = COPY[locale];
  const { auth } = useAuth();
  const {
    trainingLoad,
    liveTrainingPlan,
    trainingPlanStatus,
    refetchTrainingPlan,
    liveWeather,
  } = useWorkspace();

  const [report, setReport] = useState<PlanModelReportWire | null>(null);
  const [reportState, setReportState] = useState<"idle" | "loading" | "error">("idle");

  useEffect(() => {
    if (!apiConfigured || !auth?.accessToken) return;
    let cancelled = false;
    setReportState("loading");
    getPlanModelReport(auth.accessToken)
      .then((r) => {
        if (!cancelled) {
          setReport(r);
          setReportState("idle");
        }
      })
      .catch(() => {
        if (!cancelled) setReportState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [auth?.accessToken]);

  const agg = report?.evaluation.baseline_aggregate;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">{locale === "en" ? "Method & Evidence" : "方法與依據"}</h1>
          <p className="page-desc">{c.intro}</p>
        </div>
      </div>

      {!apiConfigured && (
        <Notice tone="neutral" icon="info" title={locale === "en" ? "Demo mode" : "展示模式"}>
          {c.demoOnly}
        </Notice>
      )}

      <div className="stack">
        {/* 1. Plan ranker */}
        <Card title={c.planTitle}>
          <p className="field-hint" style={{ marginBottom: 10 }}>{c.planDesc}</p>
          {apiConfigured && trainingPlanStatus === "loading" && !liveTrainingPlan ? (
            <Notice tone="neutral" icon="info">{c.planLoading}</Notice>
          ) : !liveTrainingPlan ? (
            <div className="row-between">
              <span className="field-hint">{c.planErr}</span>
              <Button size="sm" onClick={() => void refetchTrainingPlan()}>
                {locale === "en" ? "Retry" : "重試"}
              </Button>
            </div>
          ) : (
            <div className="stack-sm">
              <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                <Badge tone="neutral">
                  {c.reason}: {REASON_LABEL[liveTrainingPlan.reason_code]?.[locale] ?? liveTrainingPlan.reason_code}
                </Badge>
                <Badge tone={liveTrainingPlan.confidence === null ? "warning" : "good"}>
                  {c.confidence}: {liveTrainingPlan.confidence === null ? "—" : pct(liveTrainingPlan.confidence)}
                </Badge>
              </div>
              {liveTrainingPlan.abstained && (
                <Notice tone="neutral" icon="info">{c.abstain}</Notice>
              )}

              <div style={{ overflowX: "auto" }}>
                <table className="method-table">
                  <thead>
                    <tr>
                      <th>{c.candidates}</th>
                      <th style={{ textAlign: "right" }}>{locale === "en" ? "Score" : "分數"}</th>
                      <th>{locale === "en" ? "Why" : "理由"}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {liveTrainingPlan.candidates.map((cand, i) => (
                      <tr key={cand.candidate_id}>
                        <td>
                          {i === 0 && <Badge tone="good" dot>{locale === "en" ? "Top" : "首選"}</Badge>}{" "}
                          {PLAN_TYPE_LABEL[cand.workout_type]?.[locale] ?? cand.workout_type}
                          {cand.duration_minutes > 0 && (
                            <span className="field-hint">
                              {" "}· {cand.duration_minutes} min
                              {cand.distance_km ? ` · ${cand.distance_km} km` : ""}
                            </span>
                          )}
                        </td>
                        <td style={{ textAlign: "right" }} className="tnum">
                          {cand.score === null ? "—" : cand.score.toFixed(2)}
                        </td>
                        <td className="field-hint">
                          {cand.rationale.join("；") || cand.provenance_rule_ids.join(", ")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <dl className="kv-list" style={{ marginTop: 6 }}>
                <dt>{c.ratio}</dt>
                <dd>{num(liveTrainingPlan.inputs.acute_chronic_ratio)}</dd>
                <dt>{c.obsDays}</dt>
                <dd>{liveTrainingPlan.inputs.observation_days}</dd>
                <dt>{c.temp}</dt>
                <dd>
                  {liveTrainingPlan.inputs.temperature_c === null
                    ? "—"
                    : `${liveTrainingPlan.inputs.temperature_c.toFixed(1)}°C`}{" "}
                  ({liveTrainingPlan.inputs.weather_state})
                </dd>
                <dt>{c.triage}</dt>
                <dd>{liveTrainingPlan.inputs.triage_urgency ?? (locale === "en" ? "none" : "無")}</dd>
                <dt>{c.coverage}</dt>
                <dd>
                  {(["training_load", "weather", "injury_triage"] as const)
                    .map((k) => `${k}: ${liveTrainingPlan.feature_coverage[k] ? "✓" : "✕"}`)
                    .join("   ")}
                </dd>
              </dl>
              <span className="field-hint" style={{ fontSize: 11 }}>
                {liveTrainingPlan.ranker_version}
              </span>
            </div>
          )}
        </Card>

        {/* 2. Offline model evaluation */}
        <Card title={c.modelTitle}>
          <p className="field-hint" style={{ marginBottom: 10 }}>{c.modelDesc}</p>
          {!apiConfigured ? null : reportState === "loading" ? (
            <Notice tone="neutral" icon="info">{c.modelLoading}</Notice>
          ) : reportState === "error" || !report ? (
            <span className="field-hint">{c.modelErr}</span>
          ) : (
            <div className="stack-sm">
              <strong style={{ fontSize: 13 }}>{c.yourHistory}</strong>
              <dl className="kv-list">
                <dt>{c.activities}</dt>
                <dd>{report.athlete_history.completed_activities}</dd>
                <dt>{c.spanDays}</dt>
                <dd>{report.athlete_history.history_span_days ?? "—"}</dd>
                <dt>{c.sinceLast}</dt>
                <dd>{report.athlete_history.days_since_last_activity ?? "—"}</dd>
                <dt>{c.ratio}</dt>
                <dd>{num(report.athlete_history.acute_chronic_ratio)}</dd>
              </dl>

              {report.athlete_features.available && (
                <>
                  <hr className="divider" />
                  <strong style={{ fontSize: 13 }}>{c.featTitle}</strong>
                  <span className="field-hint">
                    {c.featMatchRate}: {pct(report.athlete_features.top_choice_match_rate)}
                    {" · "}{report.athlete_features.n_days} {locale === "en" ? "days" : "天"}
                  </span>
                  <div style={{ overflowX: "auto" }}>
                    <table className="method-table">
                      <thead>
                        <tr>
                          <th>{locale === "en" ? "Day" : "第 N 天"}</th>
                          <th>{c.featPredicted}</th>
                          <th>{c.featActual}</th>
                          <th>{c.featMatched}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(report.athlete_features.days ?? []).slice(-10).map((d) => (
                          <tr key={d.day_index}>
                            <td>{d.day_index}</td>
                            <td>{PLAN_TYPE_LABEL[d.predicted]?.[locale] ?? d.predicted}</td>
                            <td>{PLAN_TYPE_LABEL[d.actual]?.[locale] ?? d.actual}</td>
                            <td>{d.matched ? "✓" : "✕"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <span className="field-hint" style={{ fontSize: 11 }}>{report.athlete_features.note}</span>
                </>
              )}

              <hr className="divider" />
              <strong style={{ fontSize: 13 }}>{c.metrics}</strong>
              <span className="field-hint">
                {c.evalOn}: {report.evaluation.n_rows} · {report.evaluation.n_queries}{" "}
                {locale === "en" ? "decisions" : "個決策"} · {report.evaluation.n_groups}{" "}
                {locale === "en" ? "athletes" : "位運動員"}
              </span>
              <dl className="kv-list">
                <dt>{c.ece}</dt>
                <dd>{num(agg?.ece, 3)}</dd>
                <dt>{c.brier}</dt>
                <dd>{num(agg?.brier, 3)}</dd>
                <dt>{c.mrr}</dt>
                <dd>{num(agg?.mrr, 3)}</dd>
                <dt>{c.tcu}</dt>
                <dd>{num(agg?.top_choice_utility, 3)}</dd>
                <dt>{c.absCov}</dt>
                <dd>{pct(agg?.abstention_coverage)}</dd>
                <dt>{c.winner}</dt>
                <dd>
                  <Badge tone="good">{c.no}</Badge>
                </dd>
              </dl>
              <span className="field-hint" style={{ fontSize: 11 }}>{report.note}</span>
            </div>
          )}
        </Card>

        {/* 3. Training-load algorithm */}
        <Card title={c.loadTitle}>
          <p className="field-hint" style={{ marginBottom: 10 }}>{c.loadDesc}</p>
          <pre className="method-formula">
{`acute  = Σ session_load over last ${ACUTE_WINDOW_DAYS} days
chronic = (Σ session_load over last ${CHRONIC_WINDOW_DAYS} days) ÷ 4   ; weekly baseline
ratio   = acute ÷ chronic`}
          </pre>
          <Notice tone="neutral" icon="info" title={c.threshold}>{c.thresholdBody}</Notice>
          <strong style={{ fontSize: 13, display: "block", marginTop: 8 }}>{c.current}</strong>
          {(() => {
            const u = trainingLoad.units[0] ?? null;
            return (
              <dl className="kv-list">
                <dt>{c.acute}</dt>
                <dd className="tnum">{num(u?.acuteLoad, 0)}</dd>
                <dt>{c.chronic}</dt>
                <dd className="tnum">{num(u?.chronicLoad, 0)}</dd>
                <dt>{c.ratio}</dt>
                <dd className="tnum">{u?.loadRatio == null ? "—" : u.loadRatio.toFixed(2)}</dd>
                <dt>{c.obsDays}</dt>
                <dd>{trainingLoad.observationDays} / {CHRONIC_WINDOW_DAYS}</dd>
                <dt>{c.quality}</dt>
                <dd><DataQualityBadge quality={trainingLoad.dataQuality} /></dd>
              </dl>
            );
          })()}
        </Card>

        {/* 4. Weather-equivalent pace */}
        <Card title={c.weatherTitle}>
          <p className="field-hint" style={{ marginBottom: 10 }}>{c.weatherDesc}</p>
          {liveWeather && liveWeather.state !== "UNAVAILABLE" ? (
            <dl className="kv-list">
              <dt>{c.wNow}</dt>
              <dd className="tnum">{pct(liveWeather.speed_loss_pct)}</dd>
              <dt>{c.wVsNormal}</dt>
              <dd className="tnum">{pct(liveWeather.speed_loss_pct_relative_to_normal)}</dd>
              <dt>{c.wClimateRef}</dt>
              <dd className="tnum">
                {liveWeather.climate_normal_reference_c === null
                  ? "—"
                  : `${liveWeather.climate_normal_reference_c.toFixed(1)}°C`}
              </dd>
              <dt>{c.temp}</dt>
              <dd className="tnum">
                {liveWeather.temperature_c === null ? "—" : `${liveWeather.temperature_c.toFixed(1)}°C`} ({liveWeather.state})
              </dd>
            </dl>
          ) : (
            <span className="field-hint">{c.wUnavailable}</span>
          )}
        </Card>

        {/* 5. Safety-triage rules */}
        <Card title={c.triageTitle}>
          <p className="field-hint" style={{ marginBottom: 10 }}>{c.triageDesc}</p>
          <div style={{ overflowX: "auto" }}>
            <table className="method-table">
              <thead>
                <tr>
                  <th>{c.tUrgency}</th>
                  <th>{c.tTrigger}</th>
                  <th>{c.tRun}</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td><Badge tone="critical">EMERGENCY</Badge></td>
                  <td className="field-hint">{c.tEmergency}</td>
                  <td>{c.tNo}</td>
                </tr>
                <tr>
                  <td><Badge tone="warning">PROMPT_CLINICIAN</Badge></td>
                  <td className="field-hint">{c.tPrompt}</td>
                  <td>{c.tNo}</td>
                </tr>
                <tr>
                  <td><Badge tone="good">SELF_CARE_NEXT_STEP</Badge></td>
                  <td className="field-hint">{c.tSelfCare}</td>
                  <td>{c.tYesCaution}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </Card>

        {/* 6. Evidence library */}
        <Card title={c.evidenceTitle}>
          <p className="field-hint">{c.evidenceBody}</p>
        </Card>

        {/* 7. Version registry */}
        <Card title={c.versionsTitle}>
          <dl className="kv-list">
            <dt>{c.vRanker}</dt>
            <dd className="tnum">{liveTrainingPlan?.ranker_version ?? "deterministic-plan-ranker-v2"}</dd>
            <dt>{c.vLoad}</dt>
            <dd className="tnum">{ALGORITHM_VERSION}</dd>
            <dt>{c.vGuidance}</dt>
            <dd className="tnum">guidance-rule-2026.08.1</dd>
            <dt>{c.vTriage}</dt>
            <dd className="tnum">safety-triage-v1</dd>
            <dt>{c.vEvidence}</dt>
            <dd className="tnum">sports-medicine-v1</dd>
          </dl>
          <span className="field-hint" style={{ fontSize: 11 }}>
            <InfoTip text={locale === "en"
              ? "Every backend response carries its algorithm_version so a given number can always be traced to the exact rule set that produced it."
              : "每個後端回應都帶有 algorithm_version，任一數字都能追溯到產生它的規則版本。"} />
          </span>
        </Card>
      </div>
    </>
  );
}
