"""The facts the coach sees, assembled once.

Both conversation paths -- streaming and non-streaming -- must receive the
same facts for the same inputs. These tests exercise the assembly through
in-memory readers, so the guarantee is pinned down without a database.
"""

from __future__ import annotations

from datetime import date

from app.coach_consultation import (
    CoachConsultation,
    ConsultationRequest,
    LatestSelfReport,
)
from app.injury_guidance import EvidencePassage
from app.plan_scenario import AthleteFacts

_TODAY = date(2026, 8, 30)


class FakeFactsReader:
    def __init__(self, facts: AthleteFacts):
        self._facts = facts

    def read_athlete_facts(self, actor_id, local_date=None) -> AthleteFacts:
        return self._facts


class FakeSelfReportReader:
    def __init__(self, report: LatestSelfReport | None):
        self._report = report

    def read_latest_self_report(self, actor_id) -> LatestSelfReport | None:
        return self._report


class FakeEvidenceReader:
    def __init__(self, passages: tuple[EvidencePassage, ...] = ()):
        self._passages = passages
        self.queries: list[object] = []

    def retrieve(self, query, *, limit: int = 5) -> tuple[EvidencePassage, ...]:
        self.queries.append(query)
        return self._passages[:limit]


def _passage(evidence_id: str, title: str) -> EvidencePassage:
    return EvidencePassage(
        evidence_id=evidence_id,
        title=title,
        publisher="British Journal of Sports Medicine",
        source_url="https://example.org/" + evidence_id,
        revision_date="2020-04-01",
        license_or_provenance="reviewed",
        corpus_version="sports-medicine-v1",
        text="Reviewed guidance text.",
    )


def _facts(**overrides) -> AthleteFacts:
    base = dict(
        local_date=_TODAY,
        observation_days=20,
        acute_load=400.0,
        chronic_load=350.0,
        temperature_c=28.0,
        humidity_pct=75.0,
        weather_state="LIVE",
    )
    base.update(overrides)
    return AthleteFacts(**base)


def _consultation(
    facts: AthleteFacts | None = None,
    report: LatestSelfReport | None = None,
    passages: tuple[EvidencePassage, ...] = (),
) -> tuple[CoachConsultation, FakeEvidenceReader]:
    evidence = FakeEvidenceReader(passages)
    return (
        CoachConsultation(
            facts_reader=FakeFactsReader(facts or _facts()),
            self_report_reader=FakeSelfReportReader(report),
            evidence_reader=evidence,
        ),
        evidence,
    )


def _request(**overrides) -> ConsultationRequest:
    base = dict(
        actor_id="11111111-1111-1111-1111-111111111111",
        messages=({"role": "user", "content": "我小腿有點緊"},),
        body_part=None,
        severity_band=None,
    )
    base.update(overrides)
    return ConsultationRequest(**base)


# --------------------------------------------------------------------------
# One assembly, both paths
# --------------------------------------------------------------------------


def test_identical_requests_produce_identical_facts():
    """Streaming and non-streaming cannot diverge if they share this."""
    consultation, _ = _consultation()
    request = _request()

    assert consultation.assemble(request) == consultation.assemble(request)


def test_assembly_needs_no_database():
    consultation, _ = _consultation()

    assembled = consultation.assemble(_request())

    assert assembled.acute_load == 400.0
    assert assembled.chronic_load == 350.0
    assert assembled.temperature_c == 28.0
    assert assembled.humidity_pct == 75.0


def test_assembled_facts_carry_the_load_ratio_the_athlete_is_shown():
    consultation, _ = _consultation(facts=_facts(acute_load=532.0, chronic_load=350.0))

    assembled = consultation.assemble(_request())

    assert assembled.load_ratio == 1.52


def test_load_ratio_is_absent_rather_than_invented_without_a_baseline():
    consultation, _ = _consultation(facts=_facts(acute_load=400.0, chronic_load=None))

    assert consultation.assemble(_request()).load_ratio is None


# --------------------------------------------------------------------------
# The latest self-report is part of what the coach sees
# --------------------------------------------------------------------------


def test_the_latest_self_report_is_included():
    report = LatestSelfReport(
        local_training_date=_TODAY, has_issue=True, severity_band="MILD", body_part="calf"
    )
    consultation, _ = _consultation(report=report)

    assembled = consultation.assemble(_request())

    assert assembled.body_part == "calf"
    assert assembled.severity_band == "MILD"
    assert assembled.has_self_reported_issue is True


def test_an_explicit_focus_takes_precedence_over_the_stored_report():
    report = LatestSelfReport(
        local_training_date=_TODAY, has_issue=True, severity_band="MILD", body_part="calf"
    )
    consultation, _ = _consultation(report=report)

    assembled = consultation.assemble(_request(body_part="knee", severity_band="MODERATE"))

    assert assembled.body_part == "knee"
    assert assembled.severity_band == "MODERATE"


def test_an_athlete_with_no_report_and_no_focus_has_no_issue():
    consultation, _ = _consultation(report=None)

    assembled = consultation.assemble(_request())

    assert assembled.body_part is None
    assert assembled.has_self_reported_issue is False


# --------------------------------------------------------------------------
# Evidence comes back attributed, and no caller builds a query string
# --------------------------------------------------------------------------


def test_retrieved_evidence_is_carried_with_its_attribution():
    consultation, _ = _consultation(passages=(_passage("peace-and-love", "PEACE & LOVE"),))

    assembled = consultation.assemble(_request())

    assert len(assembled.evidence) == 1
    assert assembled.evidence[0].title == "PEACE & LOVE"
    assert assembled.evidence[0].publisher == "British Journal of Sports Medicine"
    assert assembled.evidence[0].source_url.startswith("https://")


def test_the_caller_never_assembles_a_query_itself():
    """Query construction belongs to the consultation, not to a route."""
    consultation, evidence = _consultation()

    consultation.assemble(_request(body_part="knee"))

    assert len(evidence.queries) == 1
    assert not isinstance(evidence.queries[0], str)


def test_the_focus_reaches_retrieval():
    consultation, evidence = _consultation()

    consultation.assemble(_request(body_part="knee", severity_band="MODERATE"))

    assert getattr(evidence.queries[0], "body_part", None) == "knee"


def test_the_latest_athlete_message_reaches_retrieval():
    consultation, evidence = _consultation()

    consultation.assemble(
        _request(
            messages=(
                {"role": "user", "content": "第一則"},
                {"role": "assistant", "content": "回覆"},
                {"role": "user", "content": "我膝蓋痛"},
            )
        )
    )

    assert "我膝蓋痛" in getattr(evidence.queries[0], "free_text", "")


def test_a_conversation_with_no_athlete_message_still_assembles():
    consultation, _ = _consultation()

    assembled = consultation.assemble(
        _request(messages=({"role": "assistant", "content": "你好"},))
    )

    assert assembled.acute_load == 400.0
