import json
import sys
import uuid
from pathlib import Path

from app.retrieval.bm25_index import BM25Index
from app.retrieval.embeddings import EmbeddingService
from app.retrieval.hybrid_search import HybridRetriever
from app.retrieval.metrics import mean, score_against_needs
from app.retrieval.reranker import Reranker
from app.retrieval.vector_store import VectorStore
from app.schemas.retrieval import RetrievalRequest
from scripts.resolve_labels import find_matches, norm
from scripts.run_comparison import load_labels_and_chunks

sys.stdout.reconfigure(encoding="utf-8")

QUESTIONS_PATH = Path("data/eval/retrieval_questions.json")
TARGETS = [None, 150, 250, 400]  # None = chunks exactly as Member 1's pipeline made them
TOP_K = 10
METRICS = ["recall@5", "recall@10", "mrr", "ndcg@10"]
SETUPS = ["Meaning only", "Hybrid + rerank"]


def merge_chunks(chunks, target):
    """Join neighbouring chunks from the same page until a group reaches `target` tokens."""
    if target is None:
        return list(chunks)
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

    merged = []
    for i, group in enumerate(groups):
        first = group[0]
        merged.append(first.model_copy(update={
            "chunk_id": f"{first.document_id}_T{target}_{i}",
            "text": "\n\n".join(c.text for c in group),
            "token_count": sum(c.token_count for c in group),
        }))
    return merged


def resolve_needs(q, indexed):
    """Find the right chunks for this chunking from the evidence phrases."""
    needs = []
    for phrase in q.get("evidence", []):
        needs.append([chunk.chunk_id for _, chunk in find_matches(phrase, indexed)])
    if len(needs) == 1:
        for phrase in q.get("alt_evidence", []):
            for _, chunk in find_matches(phrase, indexed):
                if chunk.chunk_id not in needs[0]:
                    needs[0].append(chunk.chunk_id)
    return [set(ids) for ids in needs]


def tidy_needs(needs):
    """Facts that now share a chunk count as one need (otherwise scoring is ambiguous)."""
    merged = []
    for need in needs:
        need = set(need)
        for other in [m for m in merged if m & need]:
            merged.remove(other)
            need |= other
        merged.append(need)
    return merged


def evaluate(variant_chunks, questions, embedding, reranker):
    indexed = [(i, c, norm(c.text)) for i, c in enumerate(variant_chunks)]
    token_by_id = {c.chunk_id: c.token_count for c in variant_chunks}

    store = VectorStore(embedding, collection_name=f"cs_{uuid.uuid4().hex}")
    bm25 = BM25Index()
    full = HybridRetriever(store, bm25, reranker, fetch_k=30)
    full.index_chunks(variant_chunks)
    searchers = {
        "Meaning only": lambda q: store.search(q, k=TOP_K),
        "Hybrid + rerank": lambda q: full.retrieve(RetrievalRequest(query=q, top_k=TOP_K)).results,
    }

    scores = {s: [] for s in SETUPS}
    context_tokens = []
    for q in questions:
        if not q.get("evidence"):
            continue
        needs = tidy_needs(resolve_needs(q, indexed))
        if not needs or any(not n for n in needs):
            print(f"  warning: {q['question_id']} could not be labelled for this chunking, skipped")
            continue
        for setup, search in searchers.items():
            results = search(q["question"])
            ranked = [r.chunk_id for r in results]
            scores[setup].append(score_against_needs(ranked, needs))
            if setup == "Hybrid + rerank":
                context_tokens.append(sum(token_by_id[r.chunk_id] for r in results[:5]))
    return scores, context_tokens


def main() -> None:
    labels, chunks = load_labels_and_chunks()  # also checks the baseline labels are fresh
    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    embedding = EmbeddingService()
    reranker = Reranker()

    summary = []
    for target in TARGETS:
        variant = merge_chunks(chunks, target)
        name = "as ingested" if target is None else f"merged to {target}"
        avg_tokens = mean(c.token_count for c in variant)
        print(f"Running: {name} ({len(variant)} chunks, average {avg_tokens:.0f} tokens)...")
        scores, context = evaluate(variant, questions, embedding, reranker)
        summary.append((name, len(variant), avg_tokens, scores, context))

    for setup in SETUPS:
        print(f"\n{setup.upper()}")
        extra = f"{'tokens in top 5':>17}" if setup == "Hybrid + rerank" else ""
        print(f"{'chunking':<18}{'chunks':>8}{'avg tok':>9}" + "".join(f"{m:>11}" for m in METRICS) + extra)
        for name, n, avg, scores, context in summary:
            row = f"{name:<18}{n:>8}{avg:>9.0f}" + "".join(
                f"{mean(s[m] for s in scores[setup]):>11.3f}" for m in METRICS)
            if setup == "Hybrid + rerank":
                row += f"{mean(context):>17.0f}"
            print(row)


if __name__ == "__main__":
    main()