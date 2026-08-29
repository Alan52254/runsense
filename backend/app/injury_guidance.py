"""Citation-bounded injury education composed after deterministic triage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, ValidationError

from app.safety_triage import TriageDecision, TriageUrgency


DISCLAIMER = "健康教練內容僅供一般資訊與自我照護參考，不能取代醫師或其他合格醫療專業人員的診斷與治療。"


@dataclass(frozen=True)
class EvidencePassage:
    evidence_id: str
    title: str
    publisher: str
    source_url: str
    revision_date: str
    license_or_provenance: str
    corpus_version: str
    text: str


@dataclass(frozen=True)
class EvidenceCitation:
    evidence_id: str
    title: str
    publisher: str
    source_url: str


@dataclass(frozen=True)
class InjuryGuidanceResult:
    urgency: TriageUrgency
    running_allowed: bool
    summary: str
    next_steps: tuple[str, ...]
    citations: tuple[EvidenceCitation, ...]
    disclaimer: str
    used_fallback: bool
    fallback_reason: str | None
    provider_name: str


class GuidanceProvider(Protocol):
    provider_name: str

    def generate(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


class _ProviderGuidance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    next_steps: list[str]
    citation_ids: list[str]


def _citations(evidence: Sequence[EvidencePassage]) -> tuple[EvidenceCitation, ...]:
    return tuple(
        EvidenceCitation(
            evidence_id=passage.evidence_id,
            title=passage.title,
            publisher=passage.publisher,
            source_url=passage.source_url,
        )
        for passage in evidence
    )


def _fallback(
    triage: TriageDecision,
    evidence: Sequence[EvidencePassage],
    provider_name: str,
    reason: str,
) -> InjuryGuidanceResult:
    return InjuryGuidanceResult(
        urgency=triage.urgency,
        running_allowed=triage.running_allowed,
        summary=triage.immediate_next_step,
        next_steps=(triage.immediate_next_step,),
        citations=_citations(evidence),
        disclaimer=DISCLAIMER,
        used_fallback=True,
        fallback_reason=reason,
        provider_name=provider_name,
    )


def compose_injury_guidance(
    triage: TriageDecision,
    evidence: Sequence[EvidencePassage],
    provider: GuidanceProvider,
) -> InjuryGuidanceResult:
    """Compose an explanation without exposing report free text to a provider."""
    evidence_by_id = {passage.evidence_id: passage for passage in evidence}
    payload = {
        "triage": {
            "urgency": triage.urgency.value,
            "matched_rule_ids": list(triage.matched_rule_ids),
            "running_allowed": triage.running_allowed,
            "immediate_next_step": triage.immediate_next_step,
        },
        "evidence": [
            {
                "evidence_id": passage.evidence_id,
                "title": passage.title,
                "publisher": passage.publisher,
                "text": passage.text,
            }
            for passage in evidence
        ],
        "output_contract": {
            "fields": ["summary", "next_steps", "citation_ids"],
            "citation_ids_must_come_from_evidence": True,
        },
    }

    try:
        output = _ProviderGuidance.model_validate(provider.generate(payload))
        if not output.summary.strip() or not output.next_steps:
            raise ValueError("empty guidance")
        if any(citation_id not in evidence_by_id for citation_id in output.citation_ids):
            raise ValueError("citation outside retrieved evidence")
    except (ValidationError, ValueError, TypeError, KeyError):
        return _fallback(triage, evidence, provider.provider_name, "INVALID_PROVIDER_OUTPUT")
    except Exception:
        return _fallback(triage, evidence, provider.provider_name, "PROVIDER_UNAVAILABLE")

    citations = tuple(
        EvidenceCitation(
            evidence_id=evidence_by_id[citation_id].evidence_id,
            title=evidence_by_id[citation_id].title,
            publisher=evidence_by_id[citation_id].publisher,
            source_url=evidence_by_id[citation_id].source_url,
        )
        for citation_id in output.citation_ids
    )
    return InjuryGuidanceResult(
        urgency=triage.urgency,
        running_allowed=triage.running_allowed,
        summary=output.summary,
        next_steps=tuple(output.next_steps),
        citations=citations,
        disclaimer=DISCLAIMER,
        used_fallback=False,
        fallback_reason=None,
        provider_name=provider.provider_name,
    )
