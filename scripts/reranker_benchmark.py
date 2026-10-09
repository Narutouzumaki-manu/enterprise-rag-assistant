import sys
import time
import uuid

from app.retrieval.bm25_index import BM25Index
from app.retrieval.embeddings import EmbeddingService
from app.retrieval.hybrid_search import HybridRetriever
from app.retrieval.metrics import mean, score_against_needs
from app.retrieval.reranker import Reranker
from app.retrieval.vector_store import VectorStore
from app.schemas.retrieval import RetrievalRequest
from scripts.run_comparison import load_labels_and_chunks
from scripts.table_experiment import linearize_table, looks_like_table

sys.stdout.reconfigure(encoding="utf-8")

TOP_K = 10
POOL = 30
USE_SENTENCE_TABLES = True
METRICS = ["recall@5", "recall@10", "mrr", "ndcg@10"]
CATEGORIES = ["fact_lookup", "table", "multi_hop"]
RERANKERS = [
    "cross-encoder/ms-marco-MiniLM-L-6-v2",   # current
    "cross-encoder/ms-marco-MiniLM-L-12-v2",  # same family, twice as deep
]


def main() -> None:
    labels, chunks = load_labels_and_chunks()
    if USE_SENTENCE_TABLES:
        chunks = [
            c.model_copy(update={"text": linearize_table(c.text)}) if looks_like_table(c.text) else c
            for c in chunks
        ]
    scorable = [q for q in labels["questions"] if q["needs"]]

    embedding = EmbeddingService()
    store = VectorStore(embedding, collection_name=f"rr_{uuid.uuid4().hex}")
    store.upsert(chunks)
    bm25 = BM25Index()
    bm25.upsert(chunks)

    rows, avg_ms, fallbacks = [], {}, {}
    for model_name in RERANKERS:
        print(f"Loading {model_name} (the first run downloads it)...")
        try:
            reranker = Reranker(model_name)
        except Exception as error:
            print(f"  could not load: {type(error).__name__}: {str(error)[:100]}\n")
            continue

        retriever = HybridRetriever(store, bm25, reranker, fetch_k=POOL)
        retriever.retrieve(RetrievalRequest(query="warm up", top_k=TOP_K))  # untimed warm-up

        timings, failed = [], 0
        for q in scorable:
            needs = [set(n["chunk_ids"]) for n in q["needs"]]
            start = time.perf_counter()
            response = retriever.retrieve(RetrievalRequest(query=q["question"], top_k=TOP_K))
            timings.append((time.perf_counter() - start) * 1000)
            if "failed" in response.reranker_model:  # silent fallback to the fused order
                failed += 1
            ranked = [r.chunk_id for r in response.results]
            rows.append({"model": model_name, "category": q["category"],
                         "scores": score_against_needs(ranked, needs)})
        avg_ms[model_name] = mean(timings)
        fallbacks[model_name] = failed

    loaded = [m for m in RERANKERS if m in avg_ms]

    print("\nRERANKER BENCHMARK (hybrid candidates, 30-chunk pool, 17 scorable questions)")
    print(f"{'reranker':<40}" + "".join(f"{m:>11}" for m in METRICS) + f"{'avg ms':>9}")
    for model_name in loaded:
        subset = [r for r in rows if r["model"] == model_name]
        values = [mean(r["scores"][m] for r in subset) for m in METRICS]
        print(f"{model_name:<40}" + "".join(f"{v:>11.3f}" for v in values) + f"{avg_ms[model_name]:>9.0f}")

    print("\nMRR BY QUESTION TYPE")
    print(f"{'reranker':<40}" + "".join(f"{c:>13}" for c in CATEGORIES))
    for model_name in loaded:
        cells = []
        for category in CATEGORIES:
            subset = [r for r in rows if r["model"] == model_name and r["category"] == category]
            cells.append(f"{mean(r['scores']['mrr'] for r in subset):>13.3f}")
        print(f"{model_name:<40}" + "".join(cells))

    for model_name in loaded:
        if fallbacks[model_name]:
            print(f"\nWARNING: {model_name} failed on {fallbacks[model_name]} queries, so those "
                  "results are the fused order, not reranked. Do not trust its row.")


if __name__ == "__main__":
    main()