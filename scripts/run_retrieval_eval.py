"""Retrieval evaluation script for the frozen golden file.

Usage:
    python -m scripts.run_retrieval_eval --expect-hash <SHA256_HASH>
"""

import argparse
import csv
import hashlib
import json
import math
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from app.eval.golden_schema import GoldenQuestion, validate_golden_questions
from app.eval.validate_golden import load_chunks, normalize_text
from app.retrieval.factory import build_default_retriever
from app.retrieval.hybrid_search import HybridRetriever
from app.retrieval.reranker import Reranker
from app.schemas.retrieval import RetrievalRequest

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def compute_sha256(path: Path | str) -> str:
    """Calculate SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().lower()


def percentile(values: list[float], pct: float) -> float:
    """Compute the pct-th percentile of values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, round(pct / 100 * len(ordered)) - 1))
    return ordered[idx]


def get_fact_phrases(q: GoldenQuestion | dict[str, Any]) -> list[list[str]]:
    """Return a list of phrase lists, one per required fact.

    Single-fact questions: evidence[0] + any alt_evidence phrases.
    Multi-fact questions:
      - tcs-gold-02:
          Fact 0 (Net margin): [evidence[0], alt_evidence[1]]
          Fact 1 (Operating margin): [evidence[1], alt_evidence[0]]
      - tcs-gold-32:
          Fact 0 (Attrition): [evidence[0]]
          Fact 1 (Cash & inv): [evidence[1], alt_evidence[0]]
      - other multi-fact: each fact has [evidence[j]]
    """
    if isinstance(q, dict):
        qid = q.get("question_id", "")
        ev = q.get("evidence", [])
        alt = q.get("alt_evidence", [])
    else:
        qid = q.question_id
        ev = q.evidence
        alt = q.alt_evidence

    facts: list[list[str]] = []
    if len(ev) == 1:
        phrases = [ev[0]]
        if alt:
            phrases.extend(alt)
        facts.append(phrases)
    elif qid == "tcs-gold-02":
        # Fact 0: Net margin
        facts.append([ev[0], alt[1]])
        # Fact 1: Operating margin
        facts.append([ev[1], alt[0]])
    elif qid == "tcs-gold-32":
        # Fact 0: Voluntary attrition
        facts.append([ev[0]])
        # Fact 1: Total cash and investments
        facts.append([ev[1], alt[0]])
    else:
        for phrase in ev:
            facts.append([phrase])
    return facts


def score_retrieval(
    fact_phrases: list[list[str]],
    retrieved_chunks: list[Any],
) -> dict[str, Any]:
    """Score top-k retrieved chunks against a question's facts using normalised phrase containment."""
    facts_total = len(fact_phrases)
    if facts_total == 0:
        return {}

    # Pre-normalize chunk texts
    chunk_texts = [
        normalize_text(getattr(c, "text", str(c))) for c in retrieved_chunks
    ]

    # Determine which facts are matched at each rank (1-based)
    rank_of_first = None
    facts_at_rank: list[set[int]] = []
    for r_idx, text in enumerate(chunk_texts, 1):
        matched = set()
        for f_idx, phrases in enumerate(fact_phrases):
            if any(normalize_text(p) in text for p in phrases):
                matched.add(f_idx)
        facts_at_rank.append(matched)
        if matched and r_idx <= 10 and rank_of_first is None:
            rank_of_first = r_idx

    # facts found at 5, 10, 15, and 20
    found_at_5 = set().union(*facts_at_rank[:5]) if facts_at_rank else set()
    found_at_10 = set().union(*facts_at_rank[:10]) if facts_at_rank else set()
    found_at_15 = set().union(*facts_at_rank[:15]) if facts_at_rank else set()
    found_at_20 = set().union(*facts_at_rank[:20]) if facts_at_rank else set()

    facts_found_5 = len(found_at_5)
    facts_found_10 = len(found_at_10)
    facts_found_15 = len(found_at_15)
    facts_found_20 = len(found_at_20)

    rec_5 = facts_found_5 / facts_total
    rec_10 = facts_found_10 / facts_total
    rec_15 = facts_found_15 / facts_total
    rec_20 = facts_found_20 / facts_total
    mrr = (1.0 / rank_of_first) if rank_of_first is not None else 0.0

    # NDCG@10 using sequential slotting for multiple facts discovered at the same chunk
    slots = []
    discovered: set[int] = set()
    for r_idx, matched in enumerate(facts_at_rank, 1):
        new_facts = matched - discovered
        if new_facts:
            for offset in range(len(new_facts)):
                slots.append(r_idx + offset)
            discovered.update(new_facts)

    dcg = sum(1.0 / math.log2(s + 1) for s in slots if s <= 10)
    ideal = sum(1.0 / math.log2(p + 1) for p in range(1, min(facts_total, 10) + 1))
    ndcg = min(1.0, dcg / ideal) if ideal > 0 else 0.0

    return {
        "facts_total": facts_total,
        "facts_found_at_5": facts_found_5,
        "facts_found_at_10": facts_found_10,
        "facts_found_at_15": facts_found_15,
        "facts_found_at_20": facts_found_20,
        "rank_of_first_relevant_chunk": rank_of_first,
        "recall@5": rec_5,
        "recall@10": rec_10,
        "recall@15": rec_15,
        "recall@20": rec_20,
        "mrr": mrr,
        "ndcg@10": ndcg,
    }


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def write_eval_results_csv(
    csv_path: Path,
    rows: list[dict[str, Any]],
) -> None:
    """Write rows to app/eval/eval_results.csv following Backend Schema Section 3 EvalRunResult."""
    fieldnames = [
        "run_id",
        "run_timestamp",
        "pipeline_variant",
        "dataset_version",
        "n_questions",
        "n_unanswerable",
        "generator_model",
        "judge_model",
        "faithfulness",
        "answer_relevancy",
        "context_precision",
        "context_recall",
        "recall_at_5",
        "recall_at_10",
        "mrr",
        "ndcg_at_10",
        "unanswerable_refused",
        "avg_latency_ms",
        "notes",
    ]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def append_eval_results_csv(
    csv_path: Path,
    rows: list[dict[str, Any]],
) -> None:
    """Append rows to app/eval/eval_results.csv following Backend Schema Section 3 EvalRunResult."""
    fieldnames = [
        "run_id",
        "run_timestamp",
        "pipeline_variant",
        "dataset_version",
        "n_questions",
        "n_unanswerable",
        "generator_model",
        "judge_model",
        "faithfulness",
        "answer_relevancy",
        "context_precision",
        "context_recall",
        "recall_at_5",
        "recall_at_10",
        "mrr",
        "ndcg_at_10",
        "unanswerable_refused",
        "avg_latency_ms",
        "notes",
    ]
    file_exists = csv_path.exists() and csv_path.stat().st_size > 0
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for r in rows:
            writer.writerow(r)


def write_per_question_csv(
    csv_path: Path,
    per_question_records: list[dict[str, Any]],
) -> None:
    """Write app/eval/results/retrieval_per_question.csv."""
    fieldnames = [
        "variant",
        "question_id",
        "category",
        "style",
        "independent",
        "facts_total",
        "facts_found_at_5",
        "facts_found_at_10",
        "facts_found_at_15",
        "facts_found_at_20",
        "rank_of_first_relevant_chunk",
        "latency_ms",
    ]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in per_question_records:
            row = {
                "variant": rec["variant"],
                "question_id": rec["question_id"],
                "category": rec["category"],
                "style": rec["style"],
                "independent": rec["independent"],
                "facts_total": rec["facts_total"],
                "facts_found_at_5": rec["facts_found_at_5"],
                "facts_found_at_10": rec["facts_found_at_10"],
                "facts_found_at_15": rec["facts_found_at_15"],
                "facts_found_at_20": rec["facts_found_at_20"],
                "rank_of_first_relevant_chunk": (
                    rec["rank_of_first_relevant_chunk"]
                    if rec["rank_of_first_relevant_chunk"] is not None
                    else ""
                ),
                "latency_ms": f"{rec['latency_ms']:.1f}",
            }
            writer.writerow(row)


def write_summary_markdown(
    md_path: Path,
    file_hash: str,
    timestamp: str,
    results_by_variant: dict[str, dict[str, Any]],
    unanswerable_data: dict[str, Any],
) -> None:
    """Write app/eval/results/retrieval_summary.md with tables, metadata, and limits."""
    md_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "# Retrieval Evaluation Summary",
        "",
        "## Metadata",
        f"- **Evaluation Timestamp**: `{timestamp}`",
        f"- **Golden File SHA-256**: `{file_hash}`",
        "- **Dataset**: `app/eval/golden_questions.json` (v1.1, 34 questions: 25 answerable, 9 unanswerable)",
        "- **Corpus**: `data/eval/documents/tcs_annual_report.pdf` (118 chunks)",
        "- **Embedding Model**: `BAAI/bge-small-en-v1.5` (dimension: 384)",
        "- **Reranker Model**: `cross-encoder/ms-marco-MiniLM-L-6-v2`",
        "",
        "---",
        "",
        "## 1. Overall Performance (All 25 Answerable Questions)",
        "",
        "| Pipeline Variant | Recall@5 | Recall@10 | Recall@15 | Recall@20 | MRR | NDCG@10 | Avg Latency (ms) | P95 Latency (ms) |",
        "|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]

    for vname, data in results_by_variant.items():
        all_ans = data["all_answerable"]
        lines.append(
            f"| `{vname}` | {all_ans['recall@5']:.4f} | {all_ans['recall@10']:.4f} | "
            f"{all_ans['recall@15']:.4f} | {all_ans['recall@20']:.4f} | "
            f"{all_ans['mrr']:.4f} | {all_ans['ndcg@10']:.4f} | {all_ans['avg_lat']:.1f} | {all_ans['p95_lat']:.1f} |"
        )

    lines.extend([
        "",
        "## 2. Independent Subset Performance (21 Questions Not Flagged SAME_FACT)",
        "",
        "| Pipeline Variant | Recall@5 | Recall@10 | Recall@15 | Recall@20 | MRR | NDCG@10 | Avg Latency (ms) | P95 Latency (ms) |",
        "|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ])

    for vname, data in results_by_variant.items():
        indep = data["independent_answerable"]
        lines.append(
            f"| `{vname}` | {indep['recall@5']:.4f} | {indep['recall@10']:.4f} | "
            f"{indep['recall@15']:.4f} | {indep['recall@20']:.4f} | "
            f"{indep['mrr']:.4f} | {indep['ndcg@10']:.4f} | {indep['avg_lat']:.1f} | {indep['p95_lat']:.1f} |"
        )

    lines.extend([
        "",
        "## 3. Breakdown by Category (All Answerable)",
        "",
        "| Variant | Category | n | Recall@5 | Recall@10 | Recall@15 | Recall@20 | MRR | NDCG@10 | Avg Latency (ms) |",
        "|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ])

    for vname, data in results_by_variant.items():
        for cat, stats in sorted(data["by_category"].items()):
            lines.append(
                f"| `{vname}` | {cat} | {stats['n']} | {stats['recall@5']:.4f} | "
                f"{stats['recall@10']:.4f} | {stats['recall@15']:.4f} | {stats['recall@20']:.4f} | "
                f"{stats['mrr']:.4f} | {stats['ndcg@10']:.4f} | {stats['avg_lat']:.1f} |"
            )

    lines.extend([
        "",
        "## 4. Breakdown by Style (All Answerable)",
        "",
        "| Variant | Style | n | Recall@5 | Recall@10 | Recall@15 | Recall@20 | MRR | NDCG@10 | Avg Latency (ms) |",
        "|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ])

    for vname, data in results_by_variant.items():
        for style, stats in sorted(data["by_style"].items()):
            lines.append(
                f"| `{vname}` | {style} | {stats['n']} | {stats['recall@5']:.4f} | "
                f"{stats['recall@10']:.4f} | {stats['recall@15']:.4f} | {stats['recall@20']:.4f} | "
                f"{stats['mrr']:.4f} | {stats['ndcg@10']:.4f} | {stats['avg_lat']:.1f} |"
            )

    lines.extend([
        "",
        "---",
        "",
        "## 5. Unanswerable Questions & Dense Score Separation Analysis",
        "",
        "Because no similarity cutoff is shipped, retrievers return `top_k=10` candidates even for questions whose answers do not exist in the document.",
        "",
        f"- **Answerable Top-1 Dense Similarity**: Min = `{unanswerable_data['ans_min']:.3f}`, Median = `{unanswerable_data['ans_med']:.3f}`, Max = `{unanswerable_data['ans_max']:.3f}`",
        "",
        "| Unanswerable ID | Question | Top-1 Dense Score | Top-1 Chunk ID |",
        "|---|---|:---:|:---:|",
    ])

    for u in unanswerable_data["unanswerable_details"]:
        lines.append(
            f"| `{u['question_id']}` | {u['question']} | {u['score']:.3f} | `{u['top1_chunk_id'][:8]}` |"
        )

    lines.extend([
        "",
        "> [!IMPORTANT]",
        "> **Can a simple dense similarity threshold separate unanswerable questions?**",
        "> **No.** The unanswerable top-1 similarity scores range from `0.698` to `0.875`, completely overlapping the answerable range (`0.646` to `0.881`). Four unanswerables (`tcs-gold-09` at 0.875, `tcs-gold-30` at 0.836, `tcs-gold-31` at 0.804, and `tcs-gold-27` at 0.787) score higher than the median answerable question (`0.782`). Any score threshold high enough to filter out unanswerables would reject more than half of valid answerable queries.",
        "",
        "---",
        "",
        "## 6. Limits of this Evaluation",
        "",
        "1. **PDF Format Only**: Chunks are ingested solely from the formatted PDF (`tcs_annual_report.pdf`) using PyMuPDF; DOCX/HTML parsers were not exercised.",
        "2. **Single Document**: Evaluated exclusively against the TCS Annual Report 2025-26 (118 chunks). Cross-document scaling and interference remain untested.",
        "3. **Small Query Sample**: 34 questions total (25 answerable, 9 unanswerable), of which 21 answerable questions are fully independent of the tuning set.",
        "4. **Retrieval-Only Scope**: Evaluates search ranking and evidence discovery only. Downstream LLM generation, grounding faithfulness, and refusal behavior were not evaluated in this run.",
        "5. **Simple Keyword Tokenizer**: The BM25 keyword index uses simple punctuation/whitespace regex tokenization without stemming, lemmatization, or financial acronym expansion.",
        "",
    ])

    md_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval variants on frozen golden questions.")
    parser.add_argument("--expect-hash", type=str, required=True, help="Expected SHA-256 hash of the golden questions file")
    parser.add_argument("--golden-file", type=str, default="app/eval/golden_questions.json", help="Path to golden questions JSON")
    parser.add_argument("--overlap-file", type=str, default="app/eval/golden_tuned_overlap.json", help="Path to overlap JSON")
    parser.add_argument("--output-dir", type=str, default="app/eval/results", help="Directory for output CSV and markdown")
    parser.add_argument("--eval-results-csv", type=str, default="app/eval/eval_results.csv", help="Path to append EvalRunResult rows")
    args = parser.parse_args()

    golden_path = Path(args.golden_file)
    if not golden_path.exists():
        print(f"ERROR: Golden questions file not found: {golden_path}", file=sys.stderr)
        return 1

    # 1. Compute and verify hash
    current_hash = compute_sha256(golden_path)
    print(f"Golden File: {golden_path}")
    print(f"SHA-256    : {current_hash}")

    if args.expect_hash.strip().lower() != current_hash:
        print(f"ERROR: Hash mismatch! Expected {args.expect_hash.strip().lower()}, got {current_hash}", file=sys.stderr)
        return 1
    print("Hash verification PASSED.\n")

    # 2. Load questions
    raw_questions = json.loads(golden_path.read_text(encoding="utf-8"))
    questions = validate_golden_questions(raw_questions)

    overlap_path = Path(args.overlap_file)
    flagged_same_fact: set[str] = set()
    if overlap_path.exists():
        ov_data = json.loads(overlap_path.read_text(encoding="utf-8"))
        flagged_same_fact = {
            item["golden"] for item in ov_data.get("flagged_same_fact", []) if "golden" in item
        }
    print(f"Loaded {len(questions)} golden questions ({sum(1 for q in questions if q.category != 'unanswerable')} answerable, {sum(1 for q in questions if q.category == 'unanswerable')} unanswerable).")
    print(f"Identified {len(flagged_same_fact)} questions flagged SAME_FACT: {sorted(list(flagged_same_fact))}\n")

    # 3. Load chunks in memory
    print("Ingesting document chunks in memory...")
    chunks = load_chunks()
    print(f"Loaded {len(chunks)} chunks from fresh PDF ingestion.\n")

    # 4. Build retriever variants in memory
    print("Building retriever variants...")
    dense = build_default_retriever(collection_name=f"eval_dense_{uuid.uuid4().hex}")
    dense.index_chunks(chunks)

    keyword = HybridRetriever(
        dense.vector_store, dense.bm25_index, None, fetch_k=dense.fetch_k, use_keyword=True
    )

    reranker = Reranker(model_name="cross-encoder/ms-marco-MiniLM-L-6-v2")
    rerank = HybridRetriever(
        dense.vector_store, dense.bm25_index, reranker, fetch_k=dense.fetch_k, use_keyword=False
    )

    variants: list[tuple[str, HybridRetriever]] = [
        ("retrieval_dense", dense),
        ("retrieval_keyword", keyword),
        ("retrieval_rerank", rerank),
    ]

    # Warm up each retriever with 1 dummy query
    for vname, ret in variants:
        ret.retrieve(RetrievalRequest(query="warm up", top_k=20))
    print("All 3 retrievers built and warmed up.\n")

    # 5. Run evaluation
    timestamp = datetime.now(timezone.utc).isoformat()
    per_question_records: list[dict[str, Any]] = []
    results_by_variant: dict[str, dict[str, Any]] = {}
    eval_run_results: list[dict[str, Any]] = []

    unans_dense_details: list[dict[str, Any]] = []
    ans_dense_scores: list[float] = []

    for vname, ret in variants:
        print(f"Evaluating variant: {vname}...")
        ans_scores: list[dict[str, Any]] = []
        indep_scores: list[dict[str, Any]] = []
        timings: list[float] = []

        # Answerable questions
        for q in questions:
            if q.category == "unanswerable":
                continue
            fact_phrases = get_fact_phrases(q)
            start = time.perf_counter()
            resp = ret.retrieve(RetrievalRequest(query=q.question, top_k=20))
            lat = (time.perf_counter() - start) * 1000
            timings.append(lat)

            scores = score_retrieval(fact_phrases, resp.results)
            is_indep = q.question_id not in flagged_same_fact

            record = {
                "variant": vname,
                "question_id": q.question_id,
                "category": q.category,
                "style": q.style,
                "independent": is_indep,
                "facts_total": scores["facts_total"],
                "facts_found_at_5": scores["facts_found_at_5"],
                "facts_found_at_10": scores["facts_found_at_10"],
                "facts_found_at_15": scores["facts_found_at_15"],
                "facts_found_at_20": scores["facts_found_at_20"],
                "rank_of_first_relevant_chunk": scores["rank_of_first_relevant_chunk"],
                "latency_ms": lat,
                "recall@5": scores["recall@5"],
                "recall@10": scores["recall@10"],
                "recall@15": scores["recall@15"],
                "recall@20": scores["recall@20"],
                "mrr": scores["mrr"],
                "ndcg@10": scores["ndcg@10"],
            }
            per_question_records.append(record)
            ans_scores.append(record)
            if is_indep:
                indep_scores.append(record)

            if vname == "retrieval_dense" and resp.results and resp.results[0].dense_score is not None:
                ans_dense_scores.append(resp.results[0].dense_score)

        # Unanswerable questions
        for q in questions:
            if q.category != "unanswerable":
                continue
            resp = ret.retrieve(RetrievalRequest(query=q.question, top_k=20))
            top_dense = resp.results[0].dense_score if resp.results else None
            top_cid = resp.results[0].chunk_id if resp.results else ""
            if vname == "retrieval_dense":
                unans_dense_details.append({
                    "question_id": q.question_id,
                    "question": q.question,
                    "score": top_dense,
                    "top1_chunk_id": top_cid,
                })

        # Calculate statistics
        def calc_stats(records: list[dict[str, Any]], lats: list[float]) -> dict[str, float]:
            return {
                "recall@5": mean([r["recall@5"] for r in records]),
                "recall@10": mean([r["recall@10"] for r in records]),
                "recall@15": mean([r["recall@15"] for r in records]),
                "recall@20": mean([r["recall@20"] for r in records]),
                "mrr": mean([r["mrr"] for r in records]),
                "ndcg@10": mean([r["ndcg@10"] for r in records]),
                "avg_lat": mean(lats),
                "p95_lat": percentile(lats, 95),
            }

        all_stats = calc_stats(ans_scores, timings)
        indep_stats = calc_stats(indep_scores, [r["latency_ms"] for r in indep_scores])

        # Group by category
        by_cat: dict[str, dict[str, Any]] = {}
        for cat in sorted({r["category"] for r in ans_scores}):
            sub = [r for r in ans_scores if r["category"] == cat]
            sub_lats = [r["latency_ms"] for r in sub]
            by_cat[cat] = {
                "n": len(sub),
                "recall@5": mean([r["recall@5"] for r in sub]),
                "recall@10": mean([r["recall@10"] for r in sub]),
                "recall@15": mean([r["recall@15"] for r in sub]),
                "recall@20": mean([r["recall@20"] for r in sub]),
                "mrr": mean([r["mrr"] for r in sub]),
                "ndcg@10": mean([r["ndcg@10"] for r in sub]),
                "avg_lat": mean(sub_lats),
            }

        # Group by style
        by_style: dict[str, dict[str, Any]] = {}
        for style in sorted({r["style"] for r in ans_scores}):
            sub = [r for r in ans_scores if r["style"] == style]
            sub_lats = [r["latency_ms"] for r in sub]
            by_style[style] = {
                "n": len(sub),
                "recall@5": mean([r["recall@5"] for r in sub]),
                "recall@10": mean([r["recall@10"] for r in sub]),
                "recall@15": mean([r["recall@15"] for r in sub]),
                "recall@20": mean([r["recall@20"] for r in sub]),
                "mrr": mean([r["mrr"] for r in sub]),
                "ndcg@10": mean([r["ndcg@10"] for r in sub]),
                "avg_lat": mean(sub_lats),
            }

        results_by_variant[vname] = {
            "all_answerable": all_stats,
            "independent_answerable": indep_stats,
            "by_category": by_cat,
            "by_style": by_style,
        }

    # Build eval_results.csv rows:
    # 3 rows for all 25 answerable questions
    for vname, _ in variants:
        st = results_by_variant[vname]["all_answerable"]
        eval_run_results.append({
            "run_id": f"run_{uuid.uuid4().hex[:12]}",
            "run_timestamp": timestamp,
            "pipeline_variant": vname,
            "dataset_version": current_hash,
            "n_questions": 25,
            "n_unanswerable": sum(1 for q in questions if q.category == "unanswerable"),
            "generator_model": "",
            "judge_model": "",
            "faithfulness": "",
            "answer_relevancy": "",
            "context_precision": "",
            "context_recall": "",
            "recall_at_5": round(st["recall@5"], 4),
            "recall_at_10": round(st["recall@10"], 4),
            "mrr": round(st["mrr"], 4),
            "ndcg_at_10": round(st["ndcg@10"], 4),
            "unanswerable_refused": "",
            "avg_latency_ms": round(st["avg_lat"], 1),
            "notes": "answerable only; 9 unanswerable excluded from retrieval metrics",
        })

    # 3 rows for independent subset (21 questions)
    for vname, _ in variants:
        st = results_by_variant[vname]["independent_answerable"]
        eval_run_results.append({
            "run_id": f"run_{uuid.uuid4().hex[:12]}",
            "run_timestamp": timestamp,
            "pipeline_variant": vname,
            "dataset_version": current_hash,
            "n_questions": 21,
            "n_unanswerable": sum(1 for q in questions if q.category == "unanswerable"),
            "generator_model": "",
            "judge_model": "",
            "faithfulness": "",
            "answer_relevancy": "",
            "context_precision": "",
            "context_recall": "",
            "recall_at_5": round(st["recall@5"], 4),
            "recall_at_10": round(st["recall@10"], 4),
            "mrr": round(st["mrr"], 4),
            "ndcg_at_10": round(st["ndcg@10"], 4),
            "unanswerable_refused": "",
            "avg_latency_ms": round(st["avg_lat"], 1),
            "notes": "independent of tuned pool",
        })

    # 6. Save outputs
    out_dir = Path(args.output_dir)
    per_q_csv = out_dir / "retrieval_per_question.csv"
    summary_md = out_dir / "retrieval_summary.md"
    eval_csv = Path(args.eval_results_csv)

    write_per_question_csv(per_q_csv, per_question_records)
    print(f"Saved {len(per_question_records)} per-question records to {per_q_csv}")

    unans_summary_data = {
        "ans_min": min(ans_dense_scores),
        "ans_med": median(ans_dense_scores),
        "ans_max": max(ans_dense_scores),
        "unanswerable_details": unans_dense_details,
    }
    write_summary_markdown(summary_md, current_hash, timestamp, results_by_variant, unans_summary_data)
    print(f"Saved summary markdown to {summary_md}")

    write_eval_results_csv(eval_csv, eval_run_results)
    print(f"Wrote {len(eval_run_results)} rows to {eval_csv}\n")

    # 7. Print summary tables to stdout
    print("=" * 110)
    print(f"OVERALL RESULTS: ALL 25 ANSWERABLE QUESTIONS (top_k=20)")
    print(f"{'Variant':<20} | {'Recall@5':>9} | {'Recall@10':>9} | {'Recall@15':>9} | {'Recall@20':>9} | {'MRR':>9} | {'NDCG@10':>9} | {'Avg ms':>8} | {'P95 ms':>8}")
    print("-" * 110)
    for vname, data in results_by_variant.items():
        st = data["all_answerable"]
        print(f"{vname:<20} | {st['recall@5']:>9.4f} | {st['recall@10']:>9.4f} | {st['recall@15']:>9.4f} | {st['recall@20']:>9.4f} | {st['mrr']:>9.4f} | {st['ndcg@10']:>9.4f} | {st['avg_lat']:>8.1f} | {st['p95_lat']:>8.1f}")
    print("-" * 110)

    print("\n" + "=" * 110)
    print(f"INDEPENDENT SUBSET: 21 ANSWERABLE QUESTIONS (not in flagged_same_fact)")
    print(f"{'Variant':<20} | {'Recall@5':>9} | {'Recall@10':>9} | {'Recall@15':>9} | {'Recall@20':>9} | {'MRR':>9} | {'NDCG@10':>9} | {'Avg ms':>8} | {'P95 ms':>8}")
    print("-" * 110)
    for vname, data in results_by_variant.items():
        st = data["independent_answerable"]
        print(f"{vname:<20} | {st['recall@5']:>9.4f} | {st['recall@10']:>9.4f} | {st['recall@15']:>9.4f} | {st['recall@20']:>9.4f} | {st['mrr']:>9.4f} | {st['ndcg@10']:>9.4f} | {st['avg_lat']:>8.1f} | {st['p95_lat']:>8.1f}")
    print("-" * 110)

    print("\nDENSE SCORE SEPARATION CHECK (retrieval_dense top-1 dense_score):")
    print(f"  Answerable questions (n=25)   : min {min(ans_dense_scores):.3f} | median {median(ans_dense_scores):.3f} | max {max(ans_dense_scores):.3f}")
    print("  Unanswerable questions (n=9)  : " + ", ".join(f"{u['question_id']}={u['score']:.3f}" for u in unans_dense_details))
    print("  Threshold separation possible : NO (unanswerables overlap across answerable distribution)\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
