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
