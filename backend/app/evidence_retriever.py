"""Provenance-preserving retrieval over reviewed guidance.

Retrieval is asked *what the situation is* -- body part, topic, recovery
phase, urgency -- and decides for itself how to satisfy that. Callers do not
build a search string; that responsibility leaking outwards is what put query
assembly into two route handlers in the first place.

Facets narrow before anything is scored. This is the property that lets the
library grow: with free-text scoring alone, a passage mentioning common words
("pain", "load", "running") competes with the one that actually covers the
Athlete's body part, so every source added made retrieval slightly worse.

The interface deliberately does not expose any retrieval-library type, so a
vector or hybrid implementation can replace this one without changing a
single caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.injury_guidance import EvidencePassage


@dataclass(frozen=True)
class EvidenceNode(EvidencePassage):
    keywords: tuple[str, ...]
    # Facets. A passage with no body parts is general: it applies whatever
    # the Athlete reported, and is what retrieval falls back to.
    body_parts: tuple[str, ...] = field(default=())
    topics: tuple[str, ...] = field(default=())
    # PROTECTION / LOADING / RETURN_TO_RUN, or None for stage-independent.
    phase: str | None = None
    # What the stage is for, and what would let the Athlete move past it.
    phase_purpose: str | None = None
    progression_criterion: str | None = None


@dataclass(frozen=True)
class EvidenceGraph:
    nodes: tuple[EvidenceNode, ...]
    edges: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class EvidenceQuery:
    """What guidance to look for, in domain terms."""

    free_text: str = ""
    body_part: str | None = None
    severity_band: str | None = None
    topic: str | None = None
    phase: str | None = None
    urgency: str | None = None


class EvidenceRetriever(Protocol):
    def retrieve(
        self, query: EvidenceQuery, *, limit: int = 6
    ) -> tuple[EvidencePassage, ...]: ...


def _mentions(haystack: str, needle: str) -> bool:
    """Body parts arrive in mixed forms -- "小腿 (Calf)", "calf", "Calf".

    Matching either way round handles both a stored facet appearing inside a
    fuller label and a label appearing inside a longer stored facet.
    """
    left = haystack.casefold()
    right = needle.casefold()
    return right in left or left in right


class GraphEvidenceRetriever:
    _GENERAL_KEYWORD = "__general__"
    # Warning-sign guidance is never narrowed away. Bone stress, cardio-
    # respiratory symptoms and the like are not confined to whichever body
    # areas a passage happens to list, and an Athlete who is filtering by
    # knee must still be able to reach them.
    _ALWAYS_REACHABLE_TOPIC = "red_flags"

    def __init__(self, graph: EvidenceGraph) -> None:
        self._nodes = {node.evidence_id: node for node in graph.nodes}
        self._edges = graph.edges
        self._has_explicit_general_markers = any(
            self._GENERAL_KEYWORD in node.keywords for node in graph.nodes
        )

    def retrieve(
        self, query: EvidenceQuery, *, limit: int = 6
    ) -> tuple[EvidencePassage, ...]:
        if limit <= 0:
            return ()

        narrowed = self._narrow(query)
        selected_ids = self._order(narrowed, query)

        # Nothing specific applied -- reviewed general guidance is still
        # cited, so the Athlete is never left with a bare answer.
        if not selected_ids:
            selected_ids = [
                node.evidence_id for node in self._nodes.values() if self._is_general(node)
            ]

        ordered = self._with_related(selected_ids, query)
        warning_ids = self._warnings()
        if query.urgency in {"EMERGENCY", "PROMPT_CLINICIAN"}:
            ordered = warning_ids + [item for item in ordered if item not in warning_ids]
        for evidence_id in warning_ids:
            if evidence_id not in ordered:
                ordered.append(evidence_id)

        return tuple(self._nodes[evidence_id] for evidence_id in ordered[:limit])

    # -- narrowing -------------------------------------------------------

    def _is_general(self, node: EvidenceNode) -> bool:
        """Which passages apply whatever the Athlete reported.

        Two conventions coexist: the corpus marks a passage general with the
        `__general__` keyword, and a facetted passage is general when it names
        no body part. Where any passage carries the explicit marker, that is
        taken as the corpus's own answer and the absence of facets is not
        second-guessed.
        """
        if self._has_explicit_general_markers:
            return self._GENERAL_KEYWORD in node.keywords
        return not node.body_parts

    def _is_warning(self, node: EvidenceNode) -> bool:
        return self._ALWAYS_REACHABLE_TOPIC in node.topics

    def _narrow(self, query: EvidenceQuery) -> list[EvidenceNode]:
        nodes = [node for node in self._nodes.values() if not self._is_warning(node)]

        if query.body_part:
            specific = [
                node
                for node in nodes
                if any(_mentions(query.body_part, part) for part in node.body_parts)
            ]
            # Only fall back to general guidance when nothing specific exists;
            # otherwise general passages would dilute a precise answer.
            nodes = specific if specific else []

        if query.phase:
            nodes = [node for node in nodes if node.phase in (None, query.phase)]

        if query.topic:
            topical = [
                node
                for node in nodes
                if any(_mentions(query.topic, topic) for topic in node.topics)
            ]
            if topical:
                nodes = topical

        return nodes

    def _warnings(self) -> list[str]:
        return [
            node.evidence_id
            for node in self._nodes.values()
            if self._is_warning(node)
        ]

    # -- ordering --------------------------------------------------------

    def _order(
        self, nodes: list[EvidenceNode], query: EvidenceQuery
    ) -> list[str]:
        """Order the narrowed set, keeping only what the words actually hit.

        Free text is a filter as well as an ordering: a passage none of the
        Athlete's words touch is not a better answer than saying nothing, so
        it is dropped rather than padded in behind the real matches. When no
        word hits anything, a facet that narrowed the set still counts as an
        answer; a query that narrowed nothing falls through to general
        guidance.
        """
        if not nodes:
            return []

        # Ties keep the library's own order, so results are stable.
        position_of = {evidence_id: index for index, evidence_id in enumerate(self._nodes)}
        narrowed_by_facet = bool(query.body_part or query.topic or query.phase)

        if not query.free_text:
            # With no words to score against, everything still standing is an
            # answer -- including a query that stated nothing at all, which is
            # someone browsing the library rather than asking a question.
            return sorted(
                (node.evidence_id for node in nodes), key=lambda i: position_of[i]
            )

        text = query.free_text.casefold()
        scored = [
            (
                -sum(
                    1
                    for keyword in node.keywords
                    if keyword != self._GENERAL_KEYWORD and keyword.casefold() in text
                ),
                position_of[node.evidence_id],
                node.evidence_id,
            )
            for node in nodes
        ]
        hits = sorted(entry for entry in scored if entry[0] < 0)
        if hits:
            return [evidence_id for _, _, evidence_id in hits]

        return (
            sorted((node.evidence_id for node in nodes), key=lambda i: position_of[i])
            if narrowed_by_facet
            else []
        )

    # -- related guidance ------------------------------------------------

    def _may_accompany(self, node: EvidenceNode, query: EvidenceQuery) -> bool:
        """Related guidance may add context, never contradict the request.

        A facet the caller stated is an explicit narrowing. Pulling in a
        neighbour that fails it would quietly widen the answer back out --
        asking for the loading stage and being handed the protection stage
        because the two are linked.
        """
        if query.phase and node.phase not in (None, query.phase):
            return False
        if query.body_part and node.body_parts:
            return any(_mentions(query.body_part, part) for part in node.body_parts)
        return True

    def _with_related(self, selected_ids: list[str], query: EvidenceQuery) -> list[str]:
        """A matched passage brings the next step it points at."""
        seeds = tuple(selected_ids)
        out = list(selected_ids)

        def consider(evidence_id: str) -> None:
            if evidence_id in out or evidence_id not in self._nodes:
                return
            if self._may_accompany(self._nodes[evidence_id], query):
                out.append(evidence_id)

        for source_id, target_id in self._edges:
            if source_id in seeds:
                consider(target_id)
            elif target_id in seeds:
                consider(source_id)
        return out
