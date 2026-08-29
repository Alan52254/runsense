from app.evidence_retriever import EvidenceGraph, EvidenceNode, GraphEvidenceRetriever


def test_graph_retrieval_expands_from_symptom_source_to_related_next_step():
    graph = EvidenceGraph(
        nodes=(
            EvidenceNode(
                evidence_id="stress-fracture-signs",
                title="Stress fracture warning signs",
                publisher="AAOS OrthoInfo",
                source_url="https://orthoinfo.aaos.org/example",
                revision_date="2026-08-29",
                license_or_provenance="link-and-manually-authored-summary",
                corpus_version="sports-medicine-v1",
                text="Localized bone pain that worsens during weight bearing needs evaluation.",
                keywords=("bone pain", "weight bearing", "stress fracture"),
            ),
            EvidenceNode(
                evidence_id="stress-fracture-next-step",
                title="Stop load and seek assessment",
                publisher="RunSense reviewed guidance",
                source_url="https://orthoinfo.aaos.org/example",
                revision_date="2026-08-29",
                license_or_provenance="human-reviewed-derived-guidance",
                corpus_version="sports-medicine-v1",
                text="Do not exercise through suspected bone stress pain.",
                keywords=("stop running", "assessment"),
            ),
        ),
        edges=(("stress-fracture-signs", "stress-fracture-next-step"),),
    )

    results = GraphEvidenceRetriever(graph).retrieve("bone pain while weight bearing", limit=4)

    assert [item.evidence_id for item in results] == [
        "stress-fracture-signs",
        "stress-fracture-next-step",
    ]
    assert all(item.corpus_version == "sports-medicine-v1" for item in results)
    assert all(item.license_or_provenance for item in results)


def _node(evidence_id, keywords):
    return EvidenceNode(
        evidence_id=evidence_id,
        title=evidence_id,
        publisher="p",
        source_url="https://example",
        revision_date="2026-08-29",
        license_or_provenance="link-and-manually-authored-summary",
        corpus_version="sports-medicine-v1",
        text="…",
        keywords=keywords,
    )


def test_retrieval_matches_a_chinese_body_part_against_bilingual_keywords():
    graph = EvidenceGraph(
        nodes=(
            _node("calf", ("小腿", "calf", "strain")),
            _node("knee", ("膝", "knee")),
            _node("general", ("__general__", "soreness")),
        ),
        edges=(),
    )

    results = GraphEvidenceRetriever(graph).retrieve("右小腿", limit=4)

    assert [r.evidence_id for r in results] == ["calf"]


def test_retrieval_falls_back_to_general_passages_when_nothing_matches():
    graph = EvidenceGraph(
        nodes=(
            _node("calf", ("小腿", "calf")),
            _node("general-1", ("__general__", "load management")),
            _node("general-2", ("__general__", "clinician")),
        ),
        edges=(),
    )

    results = GraphEvidenceRetriever(graph).retrieve("阿基里斯腱", limit=4)

    assert {r.evidence_id for r in results} == {"general-1", "general-2"}
    assert results  # never bare
