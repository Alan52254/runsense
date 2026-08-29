from __future__ import annotations

import os
import uuid
from typing import Any, Mapping

from fastapi import HTTPException
from sqlalchemy import Connection, text

from app.db import actor_transaction
from app.evidence_retriever import EvidenceGraph, EvidenceNode, GraphEvidenceRetriever
from app.guidance_providers import GroqGuidanceProvider
from app.injury_guidance import GuidanceProvider, compose_injury_guidance
from app.safety_triage import SafetyTriageInput, assess_safety_triage


_REPORT_SUMMARY = text(
    """
    SELECT severity_band, body_part
      FROM injury_reports
     WHERE id = :report_id AND athlete_id = :athlete_id
    """
)


_EVIDENCE_GRAPH = EvidenceGraph(
    nodes=(
        EvidenceNode(
            evidence_id="aaos-stress-fracture-warning-signs",
            title="Stress Fractures of the Foot and Ankle",
            publisher="AAOS OrthoInfo",
            source_url="https://orthoinfo.aaos.org/en/diseases--conditions/stress-fractures-of-the-foot-and-ankle/",
            revision_date="2026-08-29",
            license_or_provenance="link-and-manually-authored-summary; source text not ingested",
            corpus_version="sports-medicine-v1",
            text="Localized bone pain that worsens with weight bearing should not be exercised through and needs prompt assessment.",
            keywords=("bone pain", "weight bearing", "stress fracture"),
        ),
        EvidenceNode(
            evidence_id="runsense-bone-stress-next-step",
            title="Conservative next step for a bone-stress pattern",
            publisher="RunSense reviewed guidance",
            source_url="https://orthoinfo.aaos.org/en/diseases--conditions/stress-fractures-of-the-foot-and-ankle/",
            revision_date="2026-08-29",
            license_or_provenance="human-reviewed guidance derived from linked source",
            corpus_version="sports-medicine-v1",
            text="Stop impact activity and arrange assessment by a qualified clinician.",
            keywords=("stop running", "clinician assessment"),
        ),
    ),
    edges=(("aaos-stress-fracture-warning-signs", "runsense-bone-stress-next-step"),),
)


class _UnavailableGuidanceProvider:
    provider_name = "static-fallback"

    def generate(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        raise RuntimeError("hosted guidance provider is not configured")


def configured_guidance_provider() -> GuidanceProvider:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return _UnavailableGuidanceProvider()
    return GroqGuidanceProvider(
        api_key=api_key,
        model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
    )


class SqlInjuryGuidanceService:
    def __init__(self, conn: Connection, provider: GuidanceProvider | None = None) -> None:
        self._conn = conn
        self._provider = provider or configured_guidance_provider()
        self._retriever = GraphEvidenceRetriever(_EVIDENCE_GRAPH)

    def create(self, actor_id: uuid.UUID, request) -> dict:
        with actor_transaction(self._conn, str(actor_id)) as tx:
            report = tx.execute(
                _REPORT_SUMMARY,
                {"report_id": request.injury_report_id, "athlete_id": actor_id},
            ).first()
        if report is None:
            raise HTTPException(status_code=404, detail={"error": "INJURY_REPORT_NOT_FOUND"})

        triage = assess_safety_triage(
            SafetyTriageInput(
                severity_band=report.severity_band,
                body_part=report.body_part,
                unable_to_bear_weight=request.unable_to_bear_weight,
                visible_deformity=request.visible_deformity,
                uncontrolled_bleeding=request.uncontrolled_bleeding,
                chest_pain_or_breathing_difficulty=request.chest_pain_or_breathing_difficulty,
                new_numbness_or_weakness=request.new_numbness_or_weakness,
                head_injury_with_neurological_symptoms=request.head_injury_with_neurological_symptoms,
                hot_swollen_joint_with_fever=request.hot_swollen_joint_with_fever,
                collapse_confusion_or_extreme_heat_illness=request.collapse_confusion_or_extreme_heat_illness,
                localized_bone_pain_worse_with_weight_bearing=request.localized_bone_pain_worse_with_weight_bearing,
            )
        )
        query_terms = [report.body_part or "running injury"]
        if request.localized_bone_pain_worse_with_weight_bearing:
            query_terms.append("bone pain weight bearing")
        evidence = self._retriever.retrieve(" ".join(query_terms))
        guidance = compose_injury_guidance(triage, evidence, self._provider)
        return {
            "injury_report_id": request.injury_report_id,
            "urgency": guidance.urgency,
            "running_allowed": guidance.running_allowed,
            "summary": guidance.summary,
            "next_steps": list(guidance.next_steps),
            "citations": [citation.__dict__ for citation in guidance.citations],
            "disclaimer": guidance.disclaimer,
            "rule_version": triage.rule_version,
            "matched_rule_ids": list(triage.matched_rule_ids),
            "provider_name": guidance.provider_name,
            "used_fallback": guidance.used_fallback,
            "fallback_reason": guidance.fallback_reason,
        }
