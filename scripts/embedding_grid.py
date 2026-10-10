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

sys.stdout.reconfigure(encoding="utf-8")

TOP_K = 10
FETCH = 30
METRICS = ["recall@5", "recall@10", "mrr", "ndcg@10"]
SETUPS = ["Meaning only", "Hybrid (no rerank)", "Meaning + rerank", "Hybrid + rerank"]
BGE_PREFIX = "Represent this sentence for searching relevant passages: "
MODELS = [  # (model name, query prefix)
    ("all-MiniLM-L6-v2", ""),
    ("BAAI/bge-small-en-v1.5", BGE_PREFIX),
    ("BAAI/bge-base-en-v1.5", BGE_PREFIX),
]


def main() -> None:
    labels, chunks = load_labels_and_chunks()
    scorable = [q for q in labels["questions"] if q["needs"]]
    reranker = Reranker()

    results = []
    for model_name, prefix in MODELS:
        print(f"Running {model_name}...")
        embedding = EmbeddingService(model_name, query_prefix=prefix)
        store = VectorStore(embedding, collection_name=f"grid_{uuid.uuid4().hex}")
        bm25 = BM25Index()
        full = HybridRetriever(store, bm25, reranker, fetch_k=FETCH)
        full.index_chunks(chunks)
        fused_only = HybridRetriever(store, bm25, None, fetch_k=FETCH)  # same indexes, no reranker

        searchers = {
            "Meaning only": lambda q: store.search(q, k=TOP_K),
            "Hybrid (no rerank)": lambda q: fused_only.retrieve(RetrievalRequest(query=q, top_k=TOP_K)).results,
            "Meaning + rerank": lambda q: reranker.rerank(q, store.search(q, k=FETCH), top_k=TOP_K),
            "Hybrid + rerank": lambda q: full.retrieve(RetrievalRequest(query=q, top_k=TOP_K)).results,
        }
        for search in searchers.values():
            search("warm up")

        scores = {s: [] for s in SETUPS}
        timings = {s: [] for s in SETUPS}
        for q in scorable:
            needs = [set(n["chunk_ids"]) for n in q["needs"]]
            for setup, search in searchers.items():
                start = time.perf_counter()
                found = search(q["question"])
                timings[setup].append((time.perf_counter() - start) * 1000)
                scores[setup].append(score_against_needs([r.chunk_id for r in found], needs))
        results.append((model_name, embedding.dimension, scores, {s: mean(t) for s, t in timings.items()}))

    for setup in SETUPS:
        print(f"\n{setup.upper()}")
        print(f"{'model':<26}{'dim':>5}" + "".join(f"{m:>11}" for m in METRICS) + f"{'avg ms':>9}")
        for model_name, dim, scores, ms in results:
            row = "".join(f"{mean(s[m] for s in scores[setup]):>11.3f}" for m in METRICS)
            print(f"{model_name:<26}{dim:>5}{row}{ms[setup]:>9.0f}")


if __name__ == "__main__":
    main()