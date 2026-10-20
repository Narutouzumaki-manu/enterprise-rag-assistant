import json
import sys
import uuid
from pathlib import Path

from app.ingestion.pipeline import ingest_document
from app.retrieval.factory import build_default_retriever
from app.retrieval.metrics import mean, score_against_needs
from app.schemas.retrieval import RetrievalRequest

sys.stdout.reconfigure(encoding="utf-8")

PDF_PATH = "data/eval/documents/tcs_annual_report.pdf"
LABELS_PATH = Path("data/eval/golden_labels.json")
RESULTS_PATH = Path("data/eval/golden_retrieval_results.json")
TOP_K = 10
AGENT_TOP_K = 8   # what the agent uses per search
METRICS = ["recall@5", "recall@10", "mrr", "ndcg@10"]


def fact_ranks(ranked, needs):
    """For each needed fact: the position of the first chunk that holds it, or None."""
    return [
        next((pos for pos, cid in enumerate(ranked, 1) if cid in need), None)
        for need in needs
    ]


def main() -> int:
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    result = ingest_document(PDF_PATH)
    if len(result.chunks) != labels["chunk_count"]:
        print(f"STOP: {len(result.chunks)} chunks now, labels were made on {labels['chunk_count']}")
        return 1

    retriever = build_default_retriever(collection_name=f"golden_{uuid.uuid4().hex}")
    retriever.index_chunks(result.chunks)
    retriever.retrieve(RetrievalRequest(query="warm up", top_k=TOP_K))

    rows, unanswerable = [], []
    for q in labels["questions"]:
        needs = [set(n["chunk_ids"]) for n in q["needs"]]
        response = retriever.retrieve(RetrievalRequest(query=q["question"], top_k=TOP_K))
        ranked = [r.chunk_id for r in response.results]
        top1 = response.results[0].dense_score if response.results else None
        if not needs:
            unanswerable.append((q["question_id"], top1))
            continue
        ranks = fact_ranks(ranked, needs)
        rows.append({
            "question_id": q["question_id"],
            "category": q["category"],
            "scores": score_against_needs(ranked, needs),
            "fact_ranks": ranks,
            "all_in_top8": all(r is not None and r <= AGENT_TOP_K for r in ranks),
            "top1_dense": top1,
        })

    print(f"GOLDEN RETRIEVAL-ONLY ({len(rows)} scorable questions, top {TOP_K}, original question only)")
    print(f"{'':<14}" + "".join(f"{m:>11}" for m in METRICS))
    print(f"{'average':<14}" + "".join(f"{mean(r['scores'][m] for r in rows):>11.3f}" for m in METRICS))

    print("\nPER QUESTION (rank of each needed fact in the top 10, '-' = missed)")
    print(f"{'q':<13}{'category':<22}{'fact ranks':<16}{'all in top 8':>12}")
    for r in rows:
        ranks = ", ".join("-" if x is None else str(x) for x in r["fact_ranks"])
        print(f"{r['question_id']:<13}{r['category']:<22}{ranks:<16}{('yes' if r['all_in_top8'] else 'NO'):>12}")

    print("\nUNANSWERABLE (top-1 dense similarity)")
    for qid, s in unanswerable:
        print(f"  {qid}: {s:.3f}" if s is not None else f"  {qid}: no results")

    RESULTS_PATH.write_text(json.dumps(
        {"top_k": TOP_K, "scorable": len(rows), "per_question": rows}, ensure_ascii=False, indent=2
    ), encoding="utf-8")
    print("\nsaved to", RESULTS_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())