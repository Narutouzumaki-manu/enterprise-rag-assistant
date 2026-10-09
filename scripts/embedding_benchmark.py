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
SETUPS = ["Meaning only", "Hybrid + rerank"]
BGE_PREFIX = "Represent this sentence for searching relevant passages: "
MODELS = [  # (model name, query prefix)
    ("all-MiniLM-L6-v2", ""),               # current
    ("BAAI/bge-small-en-v1.5", BGE_PREFIX),  # about 130 MB
    ("BAAI/bge-base-en-v1.5", BGE_PREFIX),   # about 440 MB
    ("multi-qa-mpnet-base-dot-v1", ""),      # about 420 MB
]


def main() -> None:
    labels, chunks = load_labels_and_chunks()
    scorable = [q for q in labels["questions"] if q["needs"]]
    reranker = Reranker()  # the same reranker for every model, so only the embeddings differ

    results = []
    for model_name, prefix in MODELS:
        print(f"Loading {model_name} (the first run downloads it)...")
        try:
            embedding = EmbeddingService(model_name, query_prefix=prefix)
        except Exception as error:
            print(f"  could not load: {type(error).__name__}: {str(error)[:100]}\n")
            continue

        store = VectorStore(embedding, collection_name=f"emb_{uuid.uuid4().hex}")
        bm25 = BM25Index()
        full = HybridRetriever(store, bm25, reranker, fetch_k=FETCH)
        start = time.perf_counter()
        full.index_chunks(chunks)
        index_seconds = time.perf_counter() - start

        searchers = {
            "Meaning only": lambda q: store.search(q, k=TOP_K),
            "Hybrid + rerank": lambda q: full.retrieve(RetrievalRequest(query=q, top_k=TOP_K)).results,
        }
        for search in searchers.values():
            search("warm up")

        scores = {s: [] for s in SETUPS}
        query_ms = []
        for q in scorable:
            needs = [set(n["chunk_ids"]) for n in q["needs"]]
            for setup, search in searchers.items():
                begin = time.perf_counter()
                found = search(q["question"])
                if setup == "Meaning only":
                    query_ms.append((time.perf_counter() - begin) * 1000)
                ranked = [r.chunk_id for r in found]
                scores[setup].append(score_against_needs(ranked, needs))
        results.append((model_name, embedding.dimension, index_seconds, mean(query_ms), scores))

    for setup in SETUPS:
        print(f"\n{setup.upper()}")
        print(f"{'model':<32}{'dim':>5}" + "".join(f"{m:>11}" for m in METRICS))
        for model_name, dim, _, _, scores in results:
            row = "".join(f"{mean(s[m] for s in scores[setup]):>11.3f}" for m in METRICS)
            print(f"{model_name:<32}{dim:>5}{row}")

    print("\nCOST")
    print(f"{'model':<32}{'dim':>5}{'index build s':>15}{'query ms':>11}")
    for model_name, dim, index_seconds, ms, _ in results:
        print(f"{model_name:<32}{dim:>5}{index_seconds:>15.1f}{ms:>11.1f}")


if __name__ == "__main__":
    main()