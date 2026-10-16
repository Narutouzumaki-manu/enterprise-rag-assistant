"""Retriever node (TRD Section 9): one search per search query, merged by chunk_id.

Chunks are merged by chunk_id, never by score (scores from different queries
are not comparable). Results are interleaved across searches before the cap is
applied, so every search stays represented. Passages that address the AI
(hidden instructions) are removed before merging.
"""
from collections.abc import Callable
from typing import Protocol

from app.agents.config import AgentConfig
from app.agents.guard import quarantine
from app.agents.state import AgentState
from app.schemas.agent import AgentStep, AgentStepType
from app.schemas.retrieval import (
    RetrievalRequest,
    RetrievalResponse,
    RetrievedChunk,
)


class Retriever(Protocol):
    """Anything with retrieve(): Member 2's retriever, or MockRetriever."""

    def retrieve(self, request: RetrievalRequest) -> RetrievalResponse: ...


def interleave(per_search: list[list[RetrievedChunk]]) -> list[RetrievedChunk]:
    """Take rank 1 of every search, then rank 2, and so on; skip chunks
    already taken. Keeps each search's own order."""
    merged: list[RetrievedChunk] = []
    seen: set[str] = set()
    longest = max((len(results) for results in per_search), default=0)
    for rank in range(longest):
        for results in per_search:
            if rank < len(results):
                chunk = results[rank]
                if chunk.chunk_id not in seen:
                    seen.add(chunk.chunk_id)
                    merged.append(chunk)
    return merged


def _passages(n: int) -> str:
    return f"{n} passage" + ("" if n == 1 else "s")


def _subqueries(n: int) -> str:
    return f"{n} sub-quer" + ("y" if n == 1 else "ies")


def _describe(
    first_pass: bool,
    new_kept: int,
    total: int,
    subquery_count: int,
    errors: int,
    quarantined: int = 0,
) -> str:
    if first_pass:
        if total == 0:
            text = (
                "Search failed; no passages retrieved"
                if errors
                else "No relevant passages found"
            )
        else:
            text = f"Retrieved {_passages(total)} across {_subqueries(subquery_count)}"
    elif new_kept == 0:
        text = "No new passages found"
    else:
        text = (
            f"Found {new_kept} new passage{'' if new_kept == 1 else 's'} "
            f"({total} in total)"
        )
    if quarantined:
        noun = "passage" if quarantined == 1 else "passages"
        verb = "it contains" if quarantined == 1 else "they contain"
        text += f"; {quarantined} {noun} removed because {verb} instructions"
    return text


def make_retriever_node(
    retriever: Retriever, config: AgentConfig
) -> Callable[[AgentState], dict]:
    """Build the retriever node. Works for the first pass and for retries:
    on a retry, new chunks are merged with the evidence already in the state."""

    def retriever_node(state: AgentState) -> dict:
        queries = state["search_queries"] or [state["query"]]

        per_search: list[list[RetrievedChunk]] = []
        errors = 0
        removed_ids: set[str] = set()
        for query in queries:
            try:
                response = retriever.retrieve(
                    RetrievalRequest(query=query, top_k=state["top_k"])
                )
                results = list(response.results)
                if config.quarantine_instructions:
                    results, removed = quarantine(results)
                    removed_ids.update(chunk.chunk_id for chunk in removed)
                per_search.append(results)
            except Exception:
                # Any retriever failure becomes a trace note, never a crash.
                errors += 1
                per_search.append([])

        existing = state["retrieved_chunks"]
        existing_ids = {c.chunk_id for c in existing}
        new = [c for c in interleave(per_search) if c.chunk_id not in existing_ids]
        # New evidence first, then what we already had; the cap cuts the old tail.
        merged = (new + existing)[: config.max_evidence_chunks]
        new_kept = sum(1 for c in merged if c.chunk_id not in existing_ids)

        subquery_count = len(state["subqueries"]) or len(queries)
        step = AgentStep(
            step_type=AgentStepType.RETRIEVE,
            content=_describe(
                first_pass=not existing,
                new_kept=new_kept,
                total=len(merged),
                subquery_count=subquery_count,
                errors=errors,
                quarantined=len(removed_ids),
            ),
            metadata={
                "search_query_count": len(queries),
                "chunks_per_search": [len(results) for results in per_search],
                "chunks_after_merge": len(merged),
                "new_chunks": new_kept,
                "attempt": state["retry_count"],
                "errors": errors,
                "quarantined": len(removed_ids),
            },
        )
        return {
            "retrieved_chunks": merged,
            "step_count": state["step_count"] + 1,
            "trace": [step],
        }

    return retriever_node