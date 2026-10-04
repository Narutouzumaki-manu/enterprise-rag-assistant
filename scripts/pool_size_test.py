import sys
import uuid

from app.retrieval.bm25_index import BM25Index
from app.retrieval.embeddings import EmbeddingService
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.metrics import mean, score_against_needs
from app.retrieval.reranker import Reranker
from app.retrieval.vector_store import VectorStore
from scripts.run_comparison import load_labels_and_chunks

sys.stdout.reconfigure(encoding="utf-8")

POOL_SIZES = [5, 10, 20, 30]
TOP_K = 10
METRICS = ["recall@5", "recall@10", "mrr", "ndcg@10"]
SETUPS = ["Meaning + rerank", "Hybrid + rerank"]
REWRITES = {"q19": "Net income Q3 FY25"}  # written by us, knowing which words the table uses


def rank_text(results, wanted):
    for pos, r in enumerate(results, 1):
        if r.chunk_id in wanted:
            return f"rank {pos}"
    return "not found"


def main() -> None:
    labels, chunks = load_labels_and_chunks()
    scorable = [q for q in labels["questions"] if q["needs"]]

    print("Building the indexes...\n")
    embedding = EmbeddingService()
    store = VectorStore(embedding, collection_name=f"pool_{uuid.uuid4().hex}")
    store.upsert(chunks)
    bm25 = BM25Index()
    bm25.upsert(chunks)
    reranker = Reranker()

    def pool_for(setup, query, n):
        dense = store.search(query, k=n)
        if setup == "Meaning + rerank":
            return dense
        return reciprocal_rank_fusion(dense, bm25.search(query, k=n), limit=n)

    for n in POOL_SIZES:
        final = {s: [] for s in SETUPS}
        pool_recall = {s: [] for s in SETUPS}
        recall10_by_question = {}

        for q in scorable:
            needs = [set(x["chunk_ids"]) for x in q["needs"]]
            for setup in SETUPS:
                pool = pool_for(setup, q["question"], n)
                pool_ids = [c.chunk_id for c in pool]
                pool_recall[setup].append(
                    score_against_needs(pool_ids, needs, recall_ks=(n,), ndcg_k=n)[f"recall@{n}"]
                )
                ranked = [r.chunk_id for r in reranker.rerank(q["question"], pool, top_k=TOP_K)]
                scores = score_against_needs(ranked, needs)
                final[setup].append(scores)
                recall10_by_question.setdefault(q["question_id"], {})[setup] = scores["recall@10"]

        print(f"POOL SIZE {n} (candidates handed to the reranker)")
        print(f"{'':<18}{'pool recall':>12}" + "".join(f"{m:>11}" for m in METRICS))
        for setup in SETUPS:
            row = [mean(s[m] for s in final[setup]) for m in METRICS]
            print(f"{setup:<18}{mean(pool_recall[setup]):>12.3f}" + "".join(f"{v:>11.3f}" for v in row))
        differing = [
            f"{qid} ({v[SETUPS[0]]:.1f} vs {v[SETUPS[1]]:.1f})"
            for qid, v in recall10_by_question.items()
            if abs(v[SETUPS[0]] - v[SETUPS[1]]) > 1e-9
        ]
        print("  questions where Recall@10 differs (meaning vs hybrid):", ", ".join(differing) or "none")
        print()

    print("=" * 78)
    print("REWRITE EXAMPLE (an upper bound: we chose words we knew the table uses, so this is NOT a score)")
    by_id = {q["question_id"]: q for q in labels["questions"]}
    for qid, rewritten in REWRITES.items():
        q = by_id[qid]
        wanted = {cid for need in q["needs"] for cid in need["chunk_ids"]}
        for label, query in (("original ", q["question"]), ("rewritten", rewritten)):
            dense = store.search(query, k=len(chunks))
            sparse = bm25.search(query, k=len(chunks))
            reranked = reranker.rerank(query, pool_for("Hybrid + rerank", query, 30), top_k=30)
            print(f"{qid} {label}: {query[:80]}")
            print(f"    meaning search: {rank_text(dense, wanted)} of {len(dense)} | "
                  f"keyword search: {rank_text(sparse, wanted)} | "
                  f"hybrid + rerank (30-pool): {rank_text(reranked, wanted)}")


if __name__ == "__main__":
    main()