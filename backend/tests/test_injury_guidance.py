from app.injury_guidance import EvidencePassage, compose_injury_guidance
from app.safety_triage import TriageDecision, TriageUrgency


class AdversarialProvider:
    provider_name = "adversarial-test-provider"

    def generate(self, payload):
        return {
            "summary": "只是輕微不適，可以繼續跑。",
            "next_steps": ["繼續原課表"],
            "citation_ids": ["not-in-evidence"],
            "urgency": "SELF_CARE_NEXT_STEP",
        }


def test_provider_cannot_lower_urgency_or_invent_citations():
    triage = TriageDecision(
        urgency=TriageUrgency.EMERGENCY,
        rule_version="safety-triage-v1",
        matched_rule_ids=("RED_FLAG_CARDIORESPIRATORY",),
        running_allowed=False,
        immediate_next_step="停止跑步並立即尋求緊急醫療協助。",
    )
    evidence = (
        EvidencePassage(
            evidence_id="official-emergency-001",
            title="Emergency warning signs",
            publisher="Approved source",
            source_url="https://example.invalid/approved-source",
            revision_date="2026-08-29",
            license_or_provenance="manually-reviewed-link-only",
            corpus_version="sports-medicine-v1",
            text="Seek emergency assistance for warning signs.",
        ),
    )

    result = compose_injury_guidance(triage, evidence, AdversarialProvider())

    assert result.urgency is TriageUrgency.EMERGENCY
    assert result.running_allowed is False
    assert result.used_fallback is True
    assert result.fallback_reason == "INVALID_PROVIDER_OUTPUT"
    assert [citation.evidence_id for citation in result.citations] == ["official-emergency-001"]
    assert "緊急" in result.summary
    assert "僅供" in result.disclaimer
    assert "不能取代" in result.disclaimer
