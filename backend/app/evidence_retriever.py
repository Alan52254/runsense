"""Small provenance-preserving graph retrieval adapter.

The interface intentionally does not expose LlamaIndex types. A vector or
LlamaIndex implementation can replace this adapter without changing callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.injury_guidance import EvidencePassage


@dataclass(frozen=True)
class EvidenceNode(EvidencePassage):
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceGraph:
    nodes: tuple[EvidenceNode, ...]
    edges: tuple[tuple[str, str], ...]


class EvidenceRetriever(Protocol):
    def retrieve(self, query: str, *, limit: int = 6) -> tuple[EvidencePassage, ...]: ...


class GraphEvidenceRetriever:
    def __init__(self, graph: EvidenceGraph) -> None:
        self._nodes = {node.evidence_id: node for node in graph.nodes}
        self._edges = graph.edges

    def retrieve(self, query: str, *, limit: int = 6) -> tuple[EvidencePassage, ...]:
        if limit <= 0:
            return ()
        normalized_query = query.casefold()
        scored = []
        for position, node in enumerate(self._nodes.values()):
            score = sum(keyword.casefold() in normalized_query for keyword in node.keywords)
            if score:
                scored.append((-score, position, node.evidence_id))
        scored.sort()

        selected_ids = [evidence_id for _, _, evidence_id in scored]
        seed_ids = tuple(selected_ids)
        for source_id, target_id in self._edges:
            if source_id in seed_ids and target_id not in selected_ids and target_id in self._nodes:
                selected_ids.append(target_id)
            elif target_id in seed_ids and source_id not in selected_ids and source_id in self._nodes:
                selected_ids.append(source_id)

        return tuple(self._nodes[evidence_id] for evidence_id in selected_ids[:limit])
