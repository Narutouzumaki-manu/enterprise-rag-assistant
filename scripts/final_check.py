import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from app.retrieval import factory
from app.retrieval.factory import build_default_retriever
from app.retrieval.hybrid_search import HybridRetriever
from app.retrieval.metrics import mean, score_against_needs
from app.schemas.retrieval import RetrievalRequest
from scripts.run_comparison import load_labels_and_chunks

sys.stdout.reconfigure(encoding="utf-8")

TOP_K = 10
REPEATS = 5
METRICS = ["recall@5", "recall@10", "mrr", "ndcg@10"]
GRID_ROW = {"recall@5": 0.882, "recall@10": 0.912, "mrr": 0.753, "ndcg@10": 0.792}
RESULTS_PATH = Path("data/eval/final_results.json")


def percentile(values, pct):
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, round(pct / 100 * len(ordered)) - 1))]


def run(retriever, questions, repeats=1):
    rows, unanswerable, timings = [], [], []
    for q in questions:
        needs = [set(n["chunk_ids"]) for n in q["needs"]]
        response = None
        for _ in range(repeats):
            start = time.perf_counter()
            response = retriever.retrieve(RetrievalRequest(query=q["question"], top_k=TOP_K))
            timings.append((time.perf_counter() - start) * 1000)
        results = response.results
        top = results[0] if results else None
        if not needs:
            unanswerable.append((q["question_id"], top.dense_score if top else None))
            continue
        ranked = [r.chunk_id for r in results]
        wanted = set().union(*needs)
        rows.append({
            "question_id": q["question_id"], "category": q["category"], "style": q["style"],
            "scores": score_against_needs(ranked, needs),
            "first": next((p for p, cid in enumerate(ranked, 1) if cid in wanted), None),
            "top1_dense": top.dense_score if top else None,
        })
    return rows, unanswerable, timings


def averages(rows):
    return {m: mean(r["scores"][m] for r in rows) for m in METRICS}


def line(label, rows):
    a = averages(rows)
    return f"{label:<26}{len(rows):>4}" + "".join(f"{a[m]:>11.3f}" for m in METRICS)


def cell(row):
    if row["first"] is None:
        return "-"
    return str(row["first"]) + ("*" if row["scores"]["recall@10"] < 1 else "")


def main() -> None:
    labels, chunks = load_labels_and_chunks()
    questions = labels["questions"]

    shipped = build_default_retriever(collection_name=f"final_{uuid.uuid4().hex}")
    shipped.index_chunks(chunks)
    keyword_option = HybridRetriever(
        shipped.vector_store, shipped.bm25_index, None, fetch_k=factory.FETCH_K, use_keyword=True
    )
    for r in (shipped, keyword_option):
        r.retrieve(RetrievalRequest(query="warm up", top_k=TOP_K))

    rows, unanswerable, timings = run(shipped, questions, repeats=REPEATS)
    option_rows, _, _ = run(keyword_option, questions)

    print("SHIPPED CONFIGURATION")
    print(f"  embedding model : {factory.EMBEDDING_MODEL}")
    print(f"  keyword search  : {shipped.use_keyword}")
    print(f"  reranker        : {shipped.reranker.model_name if shipped.reranker else 'none'}")
    print(f"  candidate pool  : {shipped.fetch_k}")

    overall = averages(rows)
    matches = all(abs(overall[m] - GRID_ROW[m]) < 0.0006 for m in METRICS)
    print(f"\nOVERALL ({len(rows)} scorable questions, top {TOP_K})")
    print(f"{'':<26}{'n':>4}" + "".join(f"{m:>11}" for m in METRICS))
    print(line("shipped", rows))
    print("matches the grid's bge-small meaning-only row:", "YES" if matches else "NO (tell me)")

    p50, p95, worst = percentile(timings, 50), percentile(timings, 95), max(timings)
    print(f"\nLATENCY over {len(timings)} timings (this CPU, {len(chunks)} chunks): "
          f"p50 {p50:.0f} ms | p95 {p95:.0f} ms | max {worst:.0f} ms")

    print("\nBY CATEGORY (shipped)")
    print(f"{'':<26}{'n':>4}" + "".join(f"{m:>11}" for m in METRICS))
    for category in sorted({r["category"] for r in rows}):
        print(line(category, [r for r in rows if r["category"] == category]))

    print("\nBY STYLE: shipped (meaning only) against the keyword-fusion option")
    print(f"{'':<26}{'n':>4}" + "".join(f"{m:>11}" for m in METRICS))
    for style in sorted({r["style"] for r in rows}):
        print(line(f"{style}: shipped", [r for r in rows if r["style"] == style]))
        print(line(f"{style}: + keyword", [r for r in option_rows if r["style"] == style]))

    print("\nWHERE THE RIGHT CHUNK LANDED (position in the top 10, '-' = missed, * = not every fact found)")
    option_by_id = {r["question_id"]: r for r in option_rows}
    print(f"{'q':<5}{'category':<13}{'style':<12}{'shipped':>9}{'+ keyword':>11}")
    for r in rows:
        print(f"{r['question_id']:<5}{r['category']:<13}{r['style']:<12}"
              f"{cell(r):>9}{cell(option_by_id[r['question_id']]):>11}")

    answerable = [r["top1_dense"] for r in rows if r["top1_dense"] is not None]
    blocked = [(qid, s) for qid, s in unanswerable if s is not None]
    print("\nNO-EVIDENCE CHECK: dense similarity of the top result")
    print(f"  answerable questions   : min {min(answerable):.3f} | median {median(answerable):.3f} | max {max(answerable):.3f}")
    print("  unanswerable questions : " + ", ".join(f"{qid} {s:.3f}" for qid, s in blocked))
    every = answerable + [s for _, s in blocked]
    low, high = min(every), max(every)
    print(f"{'cutoff':>8}  {'answerable kept':>17}  {'unanswerable let through':>26}")
    for step in range(7):
        cutoff = low + (high - low) * step / 6
        kept = f"{sum(1 for s in answerable if s >= cutoff)} of {len(answerable)}"
        through = f"{sum(1 for _, s in blocked if s >= cutoff)} of {len(blocked)}"
        print(f"{cutoff:>8.3f}  {kept:>17}  {through:>26}")
    print("Only 3 unanswerable questions exist: a pattern to test, not a rule.")

    def grouped(key):
        return {
            value: {m: round(averages([r for r in rows if r[key] == value])[m], 4) for m in METRICS}
            for value in sorted({r[key] for r in rows})
        }

    RESULTS_PATH.write_text(json.dumps({
        "run_at": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "embedding_model": factory.EMBEDDING_MODEL, "use_keyword": shipped.use_keyword,
            "reranker": shipped.reranker.model_name if shipped.reranker else None,
            "fetch_k": shipped.fetch_k,
        },
        "chunk_count": len(chunks),
        "scorable_questions": len(rows),
        "overall": {m: round(overall[m], 4) for m in METRICS},
        "matches_grid_row": matches,
        "latency_ms": {"p50": round(p50, 1), "p95": round(p95, 1), "max": round(worst, 1), "timings": len(timings)},
        "by_category": grouped("category"),
        "by_style": grouped("style"),
        "per_question": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nsaved to", RESULTS_PATH)


if __name__ == "__main__":
    main()