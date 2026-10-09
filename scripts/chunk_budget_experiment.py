import sys
import uuid

import tiktoken

from app.retrieval.bm25_index import BM25Index
from app.retrieval.embeddings import EmbeddingService
from app.retrieval.hybrid_search import HybridRetriever
from app.retrieval.metrics import mean, score_against_needs
from app.retrieval.reranker import Reranker
from app.retrieval.vector_store import VectorStore
from app.schemas.retrieval import RetrievalRequest
from scripts.chunk_size_experiment import tidy_needs
from scripts.run_comparison import load_labels_and_chunks
from scripts.table_experiment import linearize_table, looks_like_table

sys.stdout.reconfigure(encoding="utf-8")

TARGETS = [None, 150, 250, 400]
BUDGETS = [400, 600, 1000, 1500]  # tokens of retrieved text the generator may read
FETCH = 30
USE_SENTENCE_TABLES = False  # True = tables rewritten as sentences (see the table experiment)

encoding = tiktoken.get_encoding("cl100k_base")


def merge_with_membership(chunks, target):
    """Merge neighbouring same-page chunks; also record which merged chunk holds each original."""
    if target is None:
        return list(chunks), {c.chunk_id: c.chunk_id for c in chunks}
    groups, current = [], []
    for chunk in chunks:
        if current and (
            chunk.metadata.page_number != current[0].metadata.page_number
            or sum(c.token_count for c in current) + chunk.token_count > target
        ):
            groups.append(current)
            current = []
        current.append(chunk)
    if current:
        groups.append(current)

    merged, member_of = [], {}
    for i, group in enumerate(groups):
        first = group[0]
        new_id = f"{first.document_id}_T{target}_{i}"
        merged.append(first.model_copy(update={
            "chunk_id": new_id,
            "text": "\n\n".join(c.text for c in group),
            "token_count": sum(c.token_count for c in group),
        }))
        for c in group:
            member_of[c.chunk_id] = new_id
    return merged, member_of


def within_budget(results, token_by_id, budget):
    """Walk down the ranking and stop at the first chunk that would exceed the budget."""
    kept, used = [], 0
    for r in results:
        cost = token_by_id[r.chunk_id]
        if used + cost > budget:
            break
        kept.append(r.chunk_id)
        used += cost
    return kept


def run_variant(chunks, labels, target, embedding, reranker):
    variant, member_of = merge_with_membership(chunks, target)
    variant = [c.model_copy(update={"token_count": len(encoding.encode(c.text))}) for c in variant]
    token_by_id = {c.chunk_id: c.token_count for c in variant}

    store = VectorStore(embedding, collection_name=f"cb_{uuid.uuid4().hex}")
    bm25 = BM25Index()
    full = HybridRetriever(store, bm25, reranker, fetch_k=FETCH)
    full.index_chunks(variant)

    recalls = {budget: [] for budget in BUDGETS}
    for q in labels["questions"]:
        if not q["needs"]:
            continue
        needs = tidy_needs([{member_of[cid] for cid in need["chunk_ids"]} for need in q["needs"]])
        results = full.retrieve(RetrievalRequest(query=q["question"], top_k=FETCH)).results
        for budget in BUDGETS:
            kept = within_budget(results, token_by_id, budget)
            n = max(len(kept), 1)
            recalls[budget].append(score_against_needs(kept, needs, recall_ks=(n,))[f"recall@{n}"])
    return variant, recalls


def main() -> None:
    labels, chunks = load_labels_and_chunks()
    if USE_SENTENCE_TABLES:
        chunks = [
            c.model_copy(update={"text": linearize_table(c.text)}) if looks_like_table(c.text) else c
            for c in chunks
        ]
    embedding = EmbeddingService()
    reranker = Reranker()

    print("SHARE OF RIGHT FACTS FOUND WITHIN A TEXT BUDGET (hybrid + rerank)")
    print("tables as sentences:", USE_SENTENCE_TABLES)
    print(f"{'chunking':<16}{'chunks':>8}{'avg tok':>9}" + "".join(f"{b:>10} tok" for b in BUDGETS))
    for target in TARGETS:
        variant, recalls = run_variant(chunks, labels, target, embedding, reranker)
        name = "as ingested" if target is None else f"merged to {target}"
        avg = mean(c.token_count for c in variant)
        print(f"{name:<16}{len(variant):>8}{avg:>9.0f}"
              + "".join(f"{mean(recalls[b]):>14.3f}" for b in BUDGETS))


if __name__ == "__main__":
    main()
    