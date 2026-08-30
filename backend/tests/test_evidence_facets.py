"""Guidance is found by what the situation is, not by a blob of text.

The failure mode this fixes: with free-text keyword scoring, a general
passage that mentions common words ("pain", "load", "running") competes with
the passage that actually covers the Athlete's body part, so growing the
library makes retrieval worse. Structured facets narrow first, so adding
sources cannot displace a specific answer.
"""

from __future__ import annotations

from app.evidence_retriever import (
    EvidenceGraph,
    EvidenceNode,
    EvidenceQuery,
    GraphEvidenceRetriever,
)


def _node(evidence_id, *, keywords=(), body_parts=(), topics=(), phase=None):
    return EvidenceNode(
        evidence_id=evidence_id,
        title=evidence_id,
        publisher="British Journal of Sports Medicine",
        source_url="https://example.org/" + evidence_id,
        revision_date="2026-08-29",
        license_or_provenance="link-and-manually-authored-summary",
        corpus_version="sports-medicine-v1",
        text="Reviewed guidance.",
        keywords=keywords,
        body_parts=body_parts,
        topics=topics,
        phase=phase,
    )


def _retriever(*nodes, edges=()):
    return GraphEvidenceRetriever(EvidenceGraph(nodes=tuple(nodes), edges=tuple(edges)))


# --------------------------------------------------------------------------
# Facets narrow before anything is scored
# --------------------------------------------------------------------------


def test_a_body_part_query_returns_that_body_parts_guidance():
    retriever = _retriever(
        _node("calf-strain", body_parts=("calf", "小腿")),
        _node("knee-pain", body_parts=("knee", "膝蓋")),
    )

    results = retriever.retrieve(EvidenceQuery(body_part="calf"), limit=4)

    assert [r.evidence_id for r in results] == ["calf-strain"]


def test_a_body_part_is_matched_across_languages():
    retriever = _retriever(
        _node("calf-strain", body_parts=("calf", "小腿")),
        _node("knee-pain", body_parts=("knee", "膝蓋")),
    )

    assert [
        r.evidence_id for r in retriever.retrieve(EvidenceQuery(body_part="小腿 (Calf)"), limit=4)
    ] == ["calf-strain"]


def test_a_recovery_phase_query_returns_only_that_stage():
    retriever = _retriever(
        _node("protect", body_parts=("calf",), phase="PROTECTION"),
        _node("load", body_parts=("calf",), phase="LOADING"),
        _node("return", body_parts=("calf",), phase="RETURN_TO_RUN"),
    )

    results = retriever.retrieve(EvidenceQuery(body_part="calf", phase="LOADING"), limit=4)

    assert [r.evidence_id for r in results] == ["load"]


def test_a_topic_query_narrows_within_a_body_part():
    retriever = _retriever(
        _node("calf-load", body_parts=("calf",), topics=("training_load",)),
        _node("calf-heat", body_parts=("calf",), topics=("heat",)),
    )

    results = retriever.retrieve(EvidenceQuery(body_part="calf", topic="heat"), limit=4)

    assert [r.evidence_id for r in results] == ["calf-heat"]


# --------------------------------------------------------------------------
# The library can grow without degrading
# --------------------------------------------------------------------------


def test_adding_unrelated_sources_does_not_displace_the_right_answer():
    """The regression the previous free-text interface could not survive."""
    specific = _node("calf-strain", keywords=("calf",), body_parts=("calf",))
    noise = [
        _node(
            f"general-{index}",
            keywords=("pain", "running", "load", "training", "recovery"),
            body_parts=(),
        )
        for index in range(25)
    ]

    results = _retriever(specific, *noise).retrieve(
        EvidenceQuery(free_text="my calf hurts when I run", body_part="calf"), limit=3
    )

    assert results[0].evidence_id == "calf-strain"


def test_free_text_orders_within_the_narrowed_set_but_cannot_widen_it():
    retriever = _retriever(
        _node("calf-a", keywords=("tight",), body_parts=("calf",)),
        _node("calf-b", keywords=("cramp",), body_parts=("calf",)),
        _node("knee-a", keywords=("tight", "cramp"), body_parts=("knee",)),
    )

    results = retriever.retrieve(
        EvidenceQuery(free_text="tight and cramping", body_part="calf"), limit=3
    )

    ids = [r.evidence_id for r in results]
    assert "knee-a" not in ids
    assert ids[0] == "calf-a"


# --------------------------------------------------------------------------
# The Athlete is never left with nothing
# --------------------------------------------------------------------------


def test_an_unmatched_body_part_falls_back_to_general_guidance():
    retriever = _retriever(
        _node("calf-strain", body_parts=("calf",)),
        _node("general-load", keywords=("__general__",)),
        _node("general-heat", keywords=("__general__",)),
    )

    results = retriever.retrieve(EvidenceQuery(body_part="elbow"), limit=4)

    assert {r.evidence_id for r in results} == {"general-load", "general-heat"}


def test_a_query_with_no_facets_at_all_still_returns_something():
    retriever = _retriever(
        _node("general-load", keywords=("__general__",)),
        _node("calf-strain", body_parts=("calf",)),
    )

    assert retriever.retrieve(EvidenceQuery(), limit=4)


def test_an_empty_library_returns_nothing_rather_than_failing():
    assert _retriever().retrieve(EvidenceQuery(body_part="calf"), limit=4) == ()


def test_a_zero_limit_returns_nothing():
    retriever = _retriever(_node("calf-strain", body_parts=("calf",)))

    assert retriever.retrieve(EvidenceQuery(body_part="calf"), limit=0) == ()


# --------------------------------------------------------------------------
# Related guidance still comes along
# --------------------------------------------------------------------------


def test_a_matched_passage_brings_its_related_next_step():
    retriever = _retriever(
        _node("bone-signs", keywords=("bone pain",), body_parts=("shin",)),
        _node("bone-next-step", keywords=("stop running",)),
        edges=(("bone-signs", "bone-next-step"),),
    )

    results = retriever.retrieve(
        EvidenceQuery(free_text="bone pain when I land", body_part="shin"), limit=4
    )

    assert [r.evidence_id for r in results] == ["bone-signs", "bone-next-step"]


def test_every_result_keeps_its_attribution():
    retriever = _retriever(_node("calf-strain", body_parts=("calf",)))

    for result in retriever.retrieve(EvidenceQuery(body_part="calf"), limit=4):
        assert result.publisher
        assert result.source_url.startswith("https://")
        assert result.corpus_version
        assert result.license_or_provenance
