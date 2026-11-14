import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.ingestion.pipeline import ingest_document
from app.retrieval.bm25_index import BM25Index
from app.retrieval.embeddings import EmbeddingService
from app.retrieval.hybrid_search import HybridRetriever
from app.retrieval.metrics import mean, score_against_needs
from app.retrieval.reranker import Reranker
from app.retrieval.vector_store import VectorStore
from app.schemas.retrieval import RetrievalRequest

sys.stdout.reconfigure(encoding="utf-8")

PDF_PATH = "data/eval/documents/tcs_annual_report.pdf"
LABELS_PATH = Path("data/eval/retrieval_labels.json")
RESULTS_PATH = Path("data/eval/comparison_results.json")
TOP_K = 10
METRICS = ["recall@5", "recall@10", "mrr", "ndcg@10"]
SETUPS = ["Meaning only", "Keyword only", "Hybrid", "Meaning + rerank", "Hybrid + rerank"]


def load_labels_and_chunks():
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    result = ingest_document(PDF_PATH)
    chunks = result.chunks
    if result.document_id != labels["document_id"] or len(chunks) != labels["chunk_count"]:
        sys.exit(
            f"The labels are stale: they were made for {labels['chunk_count']} chunks of "
            f"'{labels['document_id']}', but the pipeline now gives {len(chunks)} chunks. "
            "Run scripts.resolve_labels again."
        )
    known = {c.chunk_id for c in chunks}
    for q in labels["questions"]:
        for need in q["needs"]:
            if not set(need["chunk_ids"]) <= known:
                sys.exit(f"{q['question_id']} points at a chunk that no longer exists. "
                         "Run scripts.resolve_labels again.")
    return labels, chunks


def show_table(title, selected, with_ms=False, timings=None):
    print(title)
    header = f"{'':<18}" + "".join(f"{m:>11}" for m in METRICS)
    print(header + (f"{'avg ms':>10}" if with_ms else ""))
    for name in SETUPS:
        subset = [r for r in selected if r["setup"] == name]
        values = [mean(r["scores"][m] for r in subset) for m in METRICS]
        line = f"{name:<18}" + "".join(f"{v:>11.3f}" for v in values)
        if with_ms:
            line += f"{mean(timings[name]):>10.0f}"
        print(line)
    print()


def main() -> None:
    labels, chunks = load_labels_and_chunks()
    chunk_number = {c.chunk_id: i for i, c in enumerate(chunks)}
    print(f"{len(chunks)} chunks. Building the indexes (the first run downloads nothing new)...\n")

    embedding = EmbeddingService()
    store = VectorStore(embedding, collection_name=f"eval_{uuid.uuid4().hex}")
    bm25 = BM25Index()
    reranker = Reranker()
    full = HybridRetriever(store, bm25, reranker, fetch_k=30)
    full.index_chunks(chunks)                                 # fills BOTH indexes
    fused_only = HybridRetriever(store, bm25, None, fetch_k=30)  # same indexes, no reranker

    searchers = {
        "Meaning only": lambda q: store.search(q, k=TOP_K),
        "Keyword only": lambda q: bm25.search(q, k=TOP_K),
        "Hybrid": lambda q: fused_only.retrieve(RetrievalRequest(query=q, top_k=TOP_K)).results,
        "Meaning + rerank": lambda q: reranker.rerank(q, store.search(q, k=30), top_k=TOP_K),
        "Hybrid + rerank": lambda q: full.retrieve(RetrievalRequest(query=q, top_k=TOP_K)).results,
    }
    for search in searchers.values():  # one untimed warm-up run each
        search("warm up")

    rows, unanswerable = [], []
    timings = {name: [] for name in SETUPS}

    for q in labels["questions"]:
        needs = [set(n["chunk_ids"]) for n in q["needs"]]
        per_setup = {}
        for name, search in searchers.items():
            start = time.perf_counter()
            results = search(q["question"])
            timings[name].append((time.perf_counter() - start) * 1000)
            per_setup[name] = results
            if not needs:
                continue
            ranked = [r.chunk_id for r in results]
            try:
                scores = score_against_needs(ranked, needs)
            except ValueError as error:
                sys.exit(f"{q['question_id']}: {error}")
            wanted = set().union(*needs)
            first_hit = next((pos for pos, cid in enumerate(ranked, 1) if cid in wanted), None)
            rows.append({
                "question_id": q["question_id"], "category": q["category"], "style": q["style"],
                "setup": name, "scores": scores, "first_hit": first_hit,
            })
        if not needs:
            unanswerable.append((q, per_setup))

    n_scorable = len({r["question_id"] for r in rows})
    print("=" * 78)
    show_table(f"OVERALL ({n_scorable} scorable questions, top {TOP_K} results each)",
               rows, with_ms=True, timings=timings)

    for key, label in (("category", "BY CATEGORY"), ("style", "BY STYLE")):
        print(label)
        for value in sorted({r[key] for r in rows}):
            selected = [r for r in rows if r[key] == value]
            count = len({r["question_id"] for r in selected})
            show_table(f"{value} (n={count})", selected)

    print("WHERE EACH SETUP FOUND THE RIGHT CHUNK")
    print("(position in the top 10; '-' = missed; * = found, but not every fact was found)")
    print(f"{'q':<5}{'category':<13}" + "".join(f"{n:>17}" for n in SETUPS))
    by_question = {}
    for r in rows:
        by_question.setdefault(r["question_id"], {})[r["setup"]] = r
    for qid, per in by_question.items():
        cells = []
        for name in SETUPS:
            r = per[name]
            if r["first_hit"] is None:
                cells.append("-")
            else:
                cells.append(str(r["first_hit"]) + ("*" if r["scores"]["recall@10"] < 1 else ""))
        category = per[SETUPS[0]]["category"]
        print(f"{qid:<5}{category:<13}" + "".join(f"{c:>17}" for c in cells))

    print("\nUNANSWERABLE QUESTIONS (nothing returned is the right answer). Top 2 results:")
    for q, per in unanswerable:
        print(f"{q['question_id']} {q['question'][:70]}")
        for name, score_name in (("Meaning only", "dense_score"), ("Hybrid + rerank", "rerank_score")):
            for r in per[name][:2]:
                text = r.text.strip().replace("\n", " ")[:50]
                print(f"   {name:<16} #{chunk_number[r.chunk_id]:<4} p.{r.page_number:<3} "
                      f"{score_name}={getattr(r, score_name):.3f}  {text}...")

    summary = {
        name: {
            **{m: round(mean(r["scores"][m] for r in rows if r["setup"] == name), 4) for m in METRICS},
            "avg_ms": round(mean(timings[name]), 1),
        }
        for name in SETUPS
    }
    RESULTS_PATH.write_text(
        json.dumps({
            "run_at": datetime.now(UTC).isoformat(),
            "document_id": labels["document_id"],
            "chunk_count": len(chunks),
            "embedding_model": embedding.model_name,
            "reranker_model": reranker.model_name,
            "top_k": TOP_K,
            "scorable_questions": n_scorable,
            "overall": summary,
            "per_question": rows,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\nsaved to", RESULTS_PATH)


if __name__ == "__main__":
    main()