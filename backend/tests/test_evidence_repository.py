from types import SimpleNamespace

from app.evidence_repository import PostgresEvidenceRepository


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeConnection:
    def __init__(self):
        self.params = []

    def execute(self, statement, params):
        self.params.append(params)
        if len(self.params) == 1:
            return FakeResult(
                [
                    SimpleNamespace(
                        evidence_id="source-a",
                        title="A",
                        publisher="Publisher",
                        source_url="https://example.invalid/a",
                        revision_date="2026-08-29",
                        license_or_provenance="reviewed-link",
                        corpus_version="sports-medicine-v1",
                        text="Reviewed summary",
                        keywords=["bone pain", "weight bearing"],
                        body_parts=["shin", "小腿脛骨"],
                        topics=["bone_stress"],
                        phase="PROTECTION",
                        phase_purpose="讓修復有機會開始。",
                        progression_criterion="日常走動不再誘發症狀。",
                    )
                ]
            )
        return FakeResult([SimpleNamespace(source_id="source-a", target_id="source-b")])


def test_repository_loads_versioned_passages_and_edges_without_leaking_sql_types():
    conn = FakeConnection()

    graph = PostgresEvidenceRepository(conn).load_graph("sports-medicine-v1")

    assert graph.nodes[0].evidence_id == "source-a"
    assert graph.nodes[0].keywords == ("bone pain", "weight bearing")
    assert graph.edges == (("source-a", "source-b"),)
    assert conn.params == [
        {"corpus_version": "sports-medicine-v1"},
        {"corpus_version": "sports-medicine-v1"},
    ]


def test_repository_carries_retrieval_facets_through_to_the_graph():
    graph = PostgresEvidenceRepository(FakeConnection()).load_graph("sports-medicine-v1")

    node = graph.nodes[0]
    assert node.body_parts == ("shin", "小腿脛骨")
    assert node.topics == ("bone_stress",)
    assert node.phase == "PROTECTION"
