import sys
import uuid
from statistics import median

from app.retrieval.bm25_index import BM25Index
from app.retrieval.embeddings import EmbeddingService
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.hybrid_search import HybridRetriever
from app.retrieval.reranker import Reranker
from app.retrieval.vector_store import VectorStore
from app.schemas.retrieval import RetrievalRequest, RetrievedChunk
from scripts.run_comparison import load_labels_and_chunks

sys.stdout.reconfigure(encoding="utf-8")

DEEP_DIVE = ["q19"]  # add more question ids here to inspect them too
POOL = 30


def position_of(ranked_ids, wanted):
    for pos, chunk_id in enumerate(ranked_ids, 1):
        if chunk_id in wanted:
            return pos
    return None


def show_position(pos, total=None, missing="not found"):
    if pos is None:
        return missing
    return f"position {pos}" + (f" of {total}" if total else "")


def preview(chunk_number, r, score_name=None):
    text = r.text.strip().replace("\n", " ")[:70]
    score = ""
    if score_name and getattr(r, score_name) is not None:
        score = f" {score_name}={getattr(r, score_name):.2f}"
    return f"#{chunk_number[r.chunk_id]:<4} p.{r.page_number}{score}  {text}..."


def spread(values):
    return f"min {min(values):.2f} | median {median(values):.2f} | max {max(values):.2f}"


def main() -> None:
    labels, chunks = load_labels_and_chunks()
    chunk_by_id = {c.chunk_id: c for c in chunks}
    chunk_number = {c.chunk_id: i for i, c in enumerate(chunks)}

    print("Building the indexes...\n")
    embedding = EmbeddingService()
    store = VectorStore(embedding, collection_name=f"diag_{uuid.uuid4().hex}")
    bm25 = BM25Index()
    reranker = Reranker()
    full = HybridRetriever(store, bm25, reranker, fetch_k=POOL)
    full.index_chunks(chunks)

    def as_retrieved(chunk):
        return RetrievedChunk(
            chunk_id=chunk.chunk_id, document_id=chunk.document_id, text=chunk.text,
            page_number=chunk.metadata.page_number, section_title=chunk.metadata.section_title,
        )

    # ---------- Part A: deep dive on single questions ----------
    print("PART A: DEEP DIVE")
    by_id = {q["question_id"]: q for q in labels["questions"]}
    for qid in DEEP_DIVE:
        q = by_id[qid]
        query = q["question"]
        wanted = {cid for need in q["needs"] for cid in need["chunk_ids"]}
        print("-" * 78)
        print(f"{qid}: {query}")
        print("right chunk(s):", ", ".join(
            f"#{chunk_number[c]} (p.{chunk_by_id[c].metadata.page_number})"
            for c in sorted(wanted, key=chunk_number.get)))

        dense = store.search(query, k=len(chunks))
        sparse = bm25.search(query, k=len(chunks))
        fused = reciprocal_rank_fusion(dense, sparse)
        pool = full.retrieve(RetrievalRequest(query=query, top_k=POOL)).results
        direct = reranker.rerank(query, [as_retrieved(chunk_by_id[c]) for c in wanted], top_k=len(wanted))

        print(f"  meaning search ranks it : {show_position(position_of([r.chunk_id for r in dense], wanted), len(dense))}")
        print(f"  keyword search ranks it : {show_position(position_of([r.chunk_id for r in sparse], wanted), len(sparse))}"
              f"  (only chunks sharing a word are listed)")
        print(f"  fused list ranks it     : {show_position(position_of([r.chunk_id for r in fused], wanted), len(fused))}")
        print(f"  after rerank            : "
              f"{show_position(position_of([r.chunk_id for r in pool], wanted), len(pool), 'NOT IN THE 30-CHUNK POOL')}")
        print(f"  reranker score if shown the right chunk directly: {direct[0].rerank_score:.2f}")
        print("  top 3 by meaning search:")
        for r in dense[:3]:
            print("     ", preview(chunk_number, r))
        print("  top 3 after rerank:")
        for r in pool[:3]:
            print("     ", preview(chunk_number, r, "rerank_score"))

    # ---------- Part B: rerank scores for every question ----------
    print("\n" + "=" * 78)
    print("PART B: RERANK SCORES FOR EVERY QUESTION (hybrid + rerank, 30-chunk pool)")
    print(f"{'q':<5}{'top-1 right?':<14}{'top-1 score':>12}{'right chunk score':>19}{'right chunk rank':>18}")

    top1_answerable, right_scores, top1_unanswerable = [], [], []
    for q in labels["questions"]:
        query = q["question"]
        pool = full.retrieve(RetrievalRequest(query=query, top_k=POOL)).results
        if not pool:
            print(f"{q['question_id']:<5}no results")
            continue
        top = pool[0]

        if not q["needs"]:
            top1_unanswerable.append((q["question_id"], top.rerank_score))
            continue

        wanted = {cid for need in q["needs"] for cid in need["chunk_ids"]}
        direct = reranker.rerank(query, [as_retrieved(chunk_by_id[c]) for c in wanted], top_k=len(wanted))
        right_score = direct[0].rerank_score
        pos = position_of([r.chunk_id for r in pool], wanted)

        top1_answerable.append(top.rerank_score)
        right_scores.append(right_score)
        is_right = "yes" if top.chunk_id in wanted else "no"
        rank_text = str(pos) if pos else "not in pool"
        print(f"{q['question_id']:<5}{is_right:<14}{top.rerank_score:>12.2f}{right_score:>19.2f}{rank_text:>18}")

    print()
    print("Answerable questions, top-1 score          :", spread(top1_answerable))
    print("Answerable questions, right chunk's score  :", spread(right_scores))
    print("Unanswerable questions, top-1 score        :",
          ", ".join(f"{qid} {score:.2f}" for qid, score in top1_unanswerable))

    print("\nIf we rejected answers whose top-1 score is below a cutoff:")
    print(f"{'cutoff':>8}  {'answerable kept':>17}  {'unanswerable let through':>26}")
    for cutoff in (-6, -4, -2, 0, 2, 4):
        kept = f"{sum(1 for s in top1_answerable if s >= cutoff)} of {len(top1_answerable)}"
        through = f"{sum(1 for _, s in top1_unanswerable if s >= cutoff)} of {len(top1_unanswerable)}"
        print(f"{cutoff:>8}  {kept:>17}  {through:>26}")
    print("\nOnly 3 unanswerable questions exist, so this shows a pattern to test, not a rule.")


if __name__ == "__main__":
    main()