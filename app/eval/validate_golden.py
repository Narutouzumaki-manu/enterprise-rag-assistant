import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.eval.golden_schema import GoldenQuestion, validate_golden_questions

# Ensure stdout encodes Unicode safely (such as rupee symbols on Windows)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def normalize_text(text: str) -> str:
    """Normalize whitespace and case, unifying smart quotes and hyphens."""
    if not text:
        return ""
    text = (
        text.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u00a0", " ")
        .replace("\u00ad", "")
    )
    return re.sub(r"\s+", " ", text).strip().lower()


def extract_numbers(text: str) -> list[str]:
    """Extract numeric values (integers, decimals) from text, omitting isolated 2-digit years if part of FYxx."""
    tokens = re.findall(r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b|\b\d+(?:\.\d+)?\b", text)
    cleaned = [t.strip() for t in tokens if t.strip()]
    return cleaned


@dataclass
class PhraseMatch:
    phrase: str
    is_alt: bool
    matching_chunk_ids: list[str]
    count: int


@dataclass
class QuestionValidationResult:
    question_id: str
    category: str
    style: str
    is_unanswerable: bool
    phrase_matches: list[PhraseMatch] = field(default_factory=list)
    unique_matched_chunk_ids: list[str] = field(default_factory=list)
    distinct_pages: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.errors:
            return "ERROR"
        if self.warnings:
            return "WARN"
        return "PASS"


def load_chunks(pdf_path: str = "data/eval/documents/tcs_annual_report.pdf") -> list[Any]:
    """Load chunks from the TCS Annual Report PDF using the standard ingestion pipeline."""
    from app.ingestion.pipeline import ingest_document

    result = ingest_document(pdf_path)
    if not result.chunks:
        raise RuntimeError(
            f"Failed to ingest chunks from '{pdf_path}': {result.error_message or 'No chunks produced'}"
        )
    return result.chunks


def check_duplicates(questions: list[GoldenQuestion]) -> list[str]:
    """Check for near-duplicates: identical normalised questions or identical evidence phrases across >3 questions."""
    warnings: list[str] = []

    # 1. Identical normalised questions
    questions_by_norm: dict[str, list[str]] = {}
    for q in questions:
        norm_q = normalize_text(q.question)
        questions_by_norm.setdefault(norm_q, []).append(q.question_id)

    for norm_q, qids in sorted(questions_by_norm.items()):
        if len(qids) > 1:
            warnings.append(
                f"Identical normalised question used by {len(qids)} questions: {qids} (question text: \"{norm_q[:70]}...\")"
            )

    # 2. Identical normalised evidence phrase used by more than 3 questions
    evidence_by_norm: dict[str, list[str]] = {}
    for q in questions:
        for phrase in q.evidence:
            norm_p = normalize_text(phrase)
            if not norm_p:
                continue
            if norm_p not in evidence_by_norm:
                evidence_by_norm[norm_p] = []
            if q.question_id not in evidence_by_norm[norm_p]:
                evidence_by_norm[norm_p].append(q.question_id)

    for norm_p, qids in sorted(evidence_by_norm.items()):
        if len(qids) > 3:
            warnings.append(
                f"Identical normalised evidence phrase used by {len(qids)} questions (>3): {qids} (phrase: \"{norm_p[:70]}...\")"
            )

    return warnings


def validate_question_phrases(
    question: GoldenQuestion,
    chunks: list[Any],
) -> QuestionValidationResult:
    """Validate phrase matches, distinct pages, and numerical assertions for a single golden question against chunks."""
    is_unanswerable = question.category == "unanswerable"
    result = QuestionValidationResult(
        question_id=question.question_id,
        category=question.category,
        style=question.style,
        is_unanswerable=is_unanswerable,
    )

    # Pre-index normalized chunk texts, ids, and page numbers
    indexed_chunks = [
        (
            getattr(c, "chunk_id", str(idx)),
            getattr(c, "text", str(c)),
            normalize_text(getattr(c, "text", str(c))),
            getattr(getattr(c, "metadata", None), "page_number", None),
        )
        for idx, c in enumerate(chunks)
    ]

    matched_chunk_ids_set: set[str] = set()

    # 1. Validate evidence phrases
    for phrase in question.evidence:
        target = normalize_text(phrase)
        matching_ids = [
            cid for cid, _, norm_text, _ in indexed_chunks if target in norm_text
        ]
        count = len(matching_ids)
        result.phrase_matches.append(
            PhraseMatch(phrase=phrase, is_alt=False, matching_chunk_ids=matching_ids, count=count)
        )
        for cid in matching_ids:
            matched_chunk_ids_set.add(cid)

        if count == 0 and not is_unanswerable:
            result.errors.append(f'Evidence phrase has 0 matches: "{phrase}"')
        elif count > 3:
            result.warnings.append(
                f'Evidence phrase matched {count} chunks (>3, too generic): "{phrase}"'
            )

    # 2. Validate alt_evidence phrases
    for phrase in question.alt_evidence:
        target = normalize_text(phrase)
        matching_ids = [
            cid for cid, _, norm_text, _ in indexed_chunks if target in norm_text
        ]
        count = len(matching_ids)
        result.phrase_matches.append(
            PhraseMatch(phrase=phrase, is_alt=True, matching_chunk_ids=matching_ids, count=count)
        )
        for cid in matching_ids:
            matched_chunk_ids_set.add(cid)

        if count == 0 and not is_unanswerable:
            result.errors.append(f'Alt evidence phrase has 0 matches: "{phrase}"')
        elif count > 3:
            result.warnings.append(
                f'Alt evidence phrase matched {count} chunks (>3, too generic): "{phrase}"'
            )

    result.unique_matched_chunk_ids = sorted(list(matched_chunk_ids_set))

    # Calculate distinct pages covered
    pages = {
        page
        for cid, _, _, page in indexed_chunks
        if cid in matched_chunk_ids_set and page is not None
    }
    result.distinct_pages = sorted(list(pages))

    # 3. Check numerical facts in reference_answer ONLY when at least one evidence phrase matched a chunk
    evidence_matched = any(pm.count > 0 for pm in result.phrase_matches if not pm.is_alt)
    if not is_unanswerable and question.reference_answer and evidence_matched:
        numbers = extract_numbers(question.reference_answer)
        if numbers:
            matched_texts = [
                text
                for cid, text, _, _ in indexed_chunks
                if cid in matched_chunk_ids_set
            ]
            combined_matched_text = " ".join(matched_texts)
            norm_combined = normalize_text(combined_matched_text)

            for num in numbers:
                num_clean = num.replace(",", "").strip()
                if (
                    num.lower() not in combined_matched_text
                    and num_clean not in norm_combined
                    and num not in norm_combined
                ):
                    result.warnings.append(
                        f"Number '{num}' from reference_answer not found in any matched chunk text"
                    )

    return result


def validate_golden_file(
    path: str | Path,
    chunks: list[Any] | None = None,
    min_total: int | None = None,
    min_unanswerable: int | None = None,
    overlap_file: str | Path | None = None,
) -> tuple[list[QuestionValidationResult], dict[str, Any], list[str], int]:
    """Validate golden question file against schema, duplicate checks, threshold minimums, and chunks."""
    file_path = Path(path)
    if not file_path.exists():
        print(f"ERROR: File not found: {file_path}", file=sys.stderr)
        return [], {}, [], 1

    try:
        raw_data = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"ERROR: Failed to parse JSON from {file_path}: {exc}", file=sys.stderr)
        return [], {}, [], 1

    # 1. Schema validation
    try:
        questions = validate_golden_questions(raw_data)
    except Exception as exc:
        print(f"ERROR: Schema validation failed: {exc}", file=sys.stderr)
        return [], {}, [], 1

    # 2. Duplicate checks
    duplicate_warnings = check_duplicates(questions)

    # 3. Load chunks if not provided
    if chunks is None:
        chunks = load_chunks()

    results: list[QuestionValidationResult] = []
    total_errors = 0

    for q in questions:
        q_res = validate_question_phrases(q, chunks)
        results.append(q_res)
        total_errors += len(q_res.errors)

    # 4. Calculate totals
    totals = {
        "total_questions": len(questions),
        "answerable": sum(1 for q in questions if q.category != "unanswerable"),
        "unanswerable": sum(1 for q in questions if q.category == "unanswerable"),
        "by_category": {},
        "by_style": {},
    }
    for q in questions:
        totals["by_category"][q.category] = totals["by_category"].get(q.category, 0) + 1
        totals["by_style"][q.style] = totals["by_style"].get(q.style, 0) + 1

    # Overlap independent counts if overlap_file provided
    if overlap_file is not None:
        ov_path = Path(overlap_file)
        if not ov_path.exists():
            print(f"ERROR: Overlap file not found: {ov_path}", file=sys.stderr)
            total_errors += 1
        else:
            try:
                ov_data = json.loads(ov_path.read_text(encoding="utf-8"))
                flagged_ids = {
                    item.get("golden")
                    for item in ov_data.get("flagged_same_fact", [])
                    if item.get("golden")
                }
                indep_ans = sum(
                    1 for q in questions if q.category != "unanswerable" and q.question_id not in flagged_ids
                )
                indep_unans = sum(
                    1 for q in questions if q.category == "unanswerable" and q.question_id not in flagged_ids
                )
                totals["independent"] = {
                    "total": indep_ans + indep_unans,
                    "answerable": indep_ans,
                    "unanswerable": indep_unans,
                    "flagged_count": len(flagged_ids),
                    "flagged_ids": sorted(list(flagged_ids)),
                }
            except Exception as exc:
                print(f"ERROR: Failed to parse overlap file '{ov_path}': {exc}", file=sys.stderr)
                total_errors += 1

    # 5. Threshold checks (--min-total and --min-unanswerable)
    if min_total is not None and totals["total_questions"] < min_total:
        print(
            f"ERROR: Total questions count ({totals['total_questions']}) is below required --min-total ({min_total}).",
            file=sys.stderr,
        )
        total_errors += 1

    if min_unanswerable is not None and totals["unanswerable"] < min_unanswerable:
        print(
            f"ERROR: Unanswerable questions count ({totals['unanswerable']}) is below required --min-unanswerable ({min_unanswerable}).",
            file=sys.stderr,
        )
        total_errors += 1

    return results, totals, duplicate_warnings, total_errors


def print_validation_report(
    results: list[QuestionValidationResult],
    totals: dict[str, Any],
    duplicate_warnings: list[str],
    file_path: str | Path,
    chunk_count: int,
) -> None:
    """Print the formatted validation table, distinct pages, issues breakdown, and summary statistics."""
    print("=" * 112)
    print("GOLDEN QUESTIONS VALIDATION REPORT")
    print(f"File: {file_path} | Chunks Source: Fresh PDF ingestion ({chunk_count} chunks)")
    print("=" * 112)

    header = f"{'question_id':<14} | {'category':<20} | {'style':<10} | {'phrases':<16} | {'matched chunks':<16} | {'pages':<10} | {'status':<8}"
    print(header)
    print("-" * 112)

    for r in results:
        if r.is_unanswerable:
            phrases_summary = "0 (unanswerable)"
            chunks_summary = "0 chunks"
            pages_summary = "0 pages"
        else:
            total_phrases = len(r.phrase_matches)
            matched_phrases = sum(1 for p in r.phrase_matches if p.count > 0)
            phrases_summary = f"{matched_phrases}/{total_phrases} matched"
            chunks_summary = f"{len(r.unique_matched_chunk_ids)} chunk(s)"
            pages_summary = f"{len(r.distinct_pages)} page(s)"

        row = f"{r.question_id:<14} | {r.category:<20} | {r.style:<10} | {phrases_summary:<16} | {chunks_summary:<16} | {pages_summary:<10} | {r.status:<8}"
        print(row)

    print("-" * 112)

    # Duplicate checks warnings
    if duplicate_warnings:
        print("\nNEAR-DUPLICATE WARNINGS:")
        for dw in duplicate_warnings:
            print(f"  ⚠️  WARNING: {dw}")

    # Detailed issues section
    issues_found = any(r.errors or r.warnings for r in results)
    if issues_found:
        print("\nDETAILED ISSUES PER QUESTION:")
        for r in results:
            if r.errors or r.warnings:
                print(f"\n[{r.question_id}] ({r.category}/{r.style}):")
                for err in r.errors:
                    print(f"  ❌ ERROR: {err}")
                for warn in r.warnings:
                    print(f"  ⚠️  WARNING: {warn}")
                for pm in r.phrase_matches:
                    chunk_info = f"chunk_ids: {pm.matching_chunk_ids}" if pm.count > 0 else "0 matches"
                    tag = "alt" if pm.is_alt else "evidence"
                    print(f"     [{tag}] \"{pm.phrase[:60]}...\" -> {pm.count} match(es) ({chunk_info})")

    # Print Totals
    print("\n" + "=" * 45)
    print("SUMMARY TOTALS")
    print("=" * 45)
    print(f"Total Questions    : {totals.get('total_questions', 0)}")
    print(f"  - Answerable     : {totals.get('answerable', 0)}")
    print(f"  - Unanswerable   : {totals.get('unanswerable', 0)}")

    print("\nBy Category:")
    for cat, count in sorted(totals.get("by_category", {}).items()):
        print(f"  - {cat:<20}: {count}")

    print("\nBy Style:")
    for style, count in sorted(totals.get("by_style", {}).items()):
        print(f"  - {style:<20}: {count}")

    passed = sum(1 for r in results if r.status == "PASS")
    warned = sum(1 for r in results if r.status == "WARN")
    errored = sum(1 for r in results if r.status == "ERROR")
    print(f"\nFinal Status: {passed} PASS, {warned} WARN, {errored} ERROR")
    print("=" * 45)

    if "independent" in totals:
        ind = totals["independent"]
        print("\n" + "=" * 45)
        print("INDEPENDENT QUESTIONS (not in flagged_same_fact)")
        print("=" * 45)
        print(f"Total Independent  : {ind.get('total', 0)}")
        print(f"  - Answerable     : {ind.get('answerable', 0)}")
        print(f"  - Unanswerable   : {ind.get('unanswerable', 0)}")
        flagged_list = ind.get("flagged_ids", [])
        print(f"  - Flagged Overlap: {len(flagged_list)} ({', '.join(flagged_list)})")
        print("=" * 45)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate canonical golden questions file.")
    parser.add_argument(
        "path",
        nargs="?",
        default="app/eval/golden_questions.json",
        help="Path to golden questions JSON file (default: app/eval/golden_questions.json)",
    )
    parser.add_argument(
        "--min-total",
        type=int,
        default=None,
        help="Minimum total questions required",
    )
    parser.add_argument(
        "--min-unanswerable",
        type=int,
        default=None,
        help="Minimum unanswerable questions required",
    )
    parser.add_argument(
        "--overlap-file",
        type=str,
        default=None,
        help="Path to golden_tuned_overlap.json to calculate independent question counts",
    )
    args = parser.parse_args()

    try:
        chunks = load_chunks()
    except Exception as exc:
        print(f"ERROR: Could not load chunks: {exc}", file=sys.stderr)
        return 1

    results, totals, duplicate_warnings, total_errors = validate_golden_file(
        args.path,
        chunks=chunks,
        min_total=args.min_total,
        min_unanswerable=args.min_unanswerable,
        overlap_file=args.overlap_file,
    )
    if not results and total_errors > 0:
        return 1

    print_validation_report(results, totals, duplicate_warnings, args.path, len(chunks))

    if total_errors > 0:
        print(f"\n❌ Validation finished with {total_errors} ERROR(s). Exit code 1.")
        return 1

    print("\n✅ Validation passed without errors. Exit code 0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
