"""The reviewed guidance library, checked as data.

Growing a library is the moment retrieval quality usually slips, so these
tests read the corpus the migration ships and assert two things: that every
passage is well-formed and attributed, and that retrieving over the *whole*
library still lands on the right passage for a specific situation.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.evidence_retriever import (
    EvidenceGraph,
    EvidenceNode,
    EvidenceQuery,
    GraphEvidenceRetriever,
)

_MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations" / "versions"


def _load(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, _MIGRATIONS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_EXPANSION = _load("guidance_expansion", "0024_expand_guidance_library.py")
_ORIGINAL = _load("guidance_original", "0021_expand_evidence_graph.py")


def _node_from(row: dict) -> EvidenceNode:
    return EvidenceNode(
        evidence_id=row["evidence_id"],
        title=row["title"],
        publisher=row["publisher"],
        source_url=row["source_url"],
        revision_date=str(row.get("revision_date", "2026-08-30")),
        license_or_provenance=row.get("license_or_provenance", "reviewed"),
        corpus_version=row.get("corpus_version", "sports-medicine-v1"),
        text=row["text"],
        keywords=tuple(row.get("keywords", ())),
        body_parts=tuple(row.get("body_parts", ())),
        topics=tuple(row.get("topics", ())),
        phase=row.get("phase"),
    )


def _original_nodes() -> list[EvidenceNode]:
    """The nine passages that existed before the expansion, with the facets
    migration 0024 backfills onto them."""
    facets = _EXPANSION._EXISTING_FACETS
    nodes = []
    for row in _ORIGINAL._PASSAGES:
        row_facets = facets.get(row["evidence_id"], {})
        nodes.append(
            _node_from(
                {
                    **row,
                    "body_parts": row_facets.get("body_parts", []),
                    "topics": row_facets.get("topics", []),
                }
            )
        )
    return nodes


def _full_library() -> GraphEvidenceRetriever:
    nodes = _original_nodes() + [_node_from(row) for row in _EXPANSION._all_new_rows()]
    edges = tuple(
        (source, target)
        for source, target, _ in (
            *[(s, t, r) for s, t, r in _ORIGINAL._EDGES],
            *_EXPANSION._NEW_EDGES,
        )
    )
    known = {node.evidence_id for node in nodes}
    return GraphEvidenceRetriever(
        EvidenceGraph(
            nodes=tuple(nodes),
            edges=tuple(e for e in edges if e[0] in known and e[1] in known),
        )
    )


# --------------------------------------------------------------------------
# The corpus is well-formed
# --------------------------------------------------------------------------


def test_every_passage_is_attributed_to_a_publisher_and_a_source():
    for row in _EXPANSION._all_new_rows():
        assert row["publisher"], row["evidence_id"]
        assert str(row["source_url"]).startswith("https://"), row["evidence_id"]
        assert row["text"].strip(), row["evidence_id"]


def test_evidence_ids_are_unique_across_the_expansion():
    ids = [row["evidence_id"] for row in _EXPANSION._all_new_rows()]

    assert len(ids) == len(set(ids))


def test_every_stage_states_its_purpose_and_how_to_progress():
    staged = [row for row in _EXPANSION._all_new_rows() if row["phase"]]

    assert staged
    for row in staged:
        assert row["phase_purpose"], row["evidence_id"]
        assert row["progression_criterion"], row["evidence_id"]


def test_every_body_area_the_interface_offers_has_all_three_stages():
    by_area: dict[str, set[str]] = {}
    for row in _EXPANSION._all_new_rows():
        if not row["phase"]:
            continue
        area = row["evidence_id"].removeprefix("protocol-").rsplit("-", 1)[0]
        by_area.setdefault(area, set()).add(str(row["phase"]))

    assert set(by_area) == set(_EXPANSION._AREAS)
    for area, phases in by_area.items():
        assert phases == {"PROTECTION", "LOADING", "RETURN_TO_RUN"}, area


def test_no_passage_claims_a_diagnosis_or_names_a_medication():
    forbidden = ["診斷為", "確診", "處方", "mg", "毫克", "ibuprofen", "布洛芬"]
    for row in _EXPANSION._all_new_rows():
        lowered = row["text"].casefold()
        for term in forbidden:
            assert term.casefold() not in lowered, f"{row['evidence_id']} mentions {term}"


def test_every_relationship_points_at_a_passage_that_exists():
    known = {row["evidence_id"] for row in _EXPANSION._all_new_rows()} | set(
        _EXPANSION._EXISTING_FACETS
    )

    for source_id, target_id, _ in _EXPANSION._NEW_EDGES:
        assert source_id in known, source_id
        assert target_id in known, target_id


# --------------------------------------------------------------------------
# Retrieval over the whole library still lands on the right passage
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body_part,expected_area",
    [
        ("膝蓋 (Knee)", "knee"),
        ("阿基里斯腱 (Achilles)", "achilles"),
        ("足底筋膜 (Plantar)", "plantar"),
        ("小腿脛骨 (Shin Splints)", "shin"),
        ("大腿後側 (Hamstring)", "hamstring"),
        ("髖關節 (Hip)", "hip"),
    ],
)
def test_each_reported_area_reaches_its_own_guidance(body_part, expected_area):
    results = _full_library().retrieve(EvidenceQuery(body_part=body_part), limit=8)

    assert results
    assert any(expected_area in result.evidence_id for result in results)


@pytest.mark.parametrize("phase", ["PROTECTION", "LOADING", "RETURN_TO_RUN"])
def test_a_stage_query_returns_that_stage_for_that_area(phase):
    results = _full_library().retrieve(
        EvidenceQuery(body_part="calf", phase=phase), limit=8
    )

    staged = [result for result in results if result.evidence_id.startswith("protocol-calf-")]
    assert staged
    assert all(phase.lower() in result.evidence_id for result in staged)


def test_the_expanded_library_does_not_bury_the_original_passages():
    """Precision on what was already covered must not regress."""
    results = _full_library().retrieve(
        EvidenceQuery(free_text="我的膝蓋在跑步時前側會痛", body_part="膝蓋 (Knee)"), limit=8
    )

    assert any(r.evidence_id == "aaos-runners-knee-load-management" for r in results)


def test_a_body_area_query_never_returns_another_areas_protocol():
    results = _full_library().retrieve(EvidenceQuery(body_part="膝蓋 (Knee)"), limit=12)

    other_areas = {"plantar", "hamstring", "hip", "achilles"}
    for result in results:
        if not result.evidence_id.startswith("protocol-"):
            continue
        area = result.evidence_id.removeprefix("protocol-").rsplit("-", 1)[0]
        assert area not in other_areas, result.evidence_id


def test_an_unmatched_area_still_returns_general_guidance():
    results = _full_library().retrieve(EvidenceQuery(body_part="手肘"), limit=6)

    assert results
    assert all(not result.body_parts for result in results)
