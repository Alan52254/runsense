from __future__ import annotations

from sqlalchemy import Connection, text

from app.evidence_retriever import EvidenceGraph, EvidenceNode


_SELECT_PASSAGES = text(
    """
    SELECT evidence_id, title, publisher, source_url, revision_date,
           license_or_provenance, corpus_version, text, keywords,
           body_parts, topics, phase, phase_purpose, progression_criterion
      FROM evidence_passages
     WHERE corpus_version = :corpus_version AND approved = true
     ORDER BY evidence_id
    """
)

_SELECT_EDGES = text(
    """
    SELECT edge.source_id, edge.target_id
      FROM evidence_edges edge
      JOIN evidence_passages source ON source.evidence_id = edge.source_id
     WHERE source.corpus_version = :corpus_version
     ORDER BY edge.source_id, edge.target_id
    """
)


class PostgresEvidenceRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def load_graph(self, corpus_version: str) -> EvidenceGraph:
        passage_rows = self._conn.execute(
            _SELECT_PASSAGES, {"corpus_version": corpus_version}
        ).all()
        edge_rows = self._conn.execute(
            _SELECT_EDGES, {"corpus_version": corpus_version}
        ).all()
        return EvidenceGraph(
            nodes=tuple(
                EvidenceNode(
                    evidence_id=row.evidence_id,
                    title=row.title,
                    publisher=row.publisher,
                    source_url=row.source_url,
                    revision_date=str(row.revision_date),
                    license_or_provenance=row.license_or_provenance,
                    corpus_version=row.corpus_version,
                    text=row.text,
                    keywords=tuple(row.keywords),
                    body_parts=tuple(row.body_parts or ()),
                    topics=tuple(row.topics or ()),
                    phase=row.phase,
                    phase_purpose=row.phase_purpose,
                    progression_criterion=row.progression_criterion,
                )
                for row in passage_rows
            ),
            edges=tuple((row.source_id, row.target_id) for row in edge_rows),
        )
