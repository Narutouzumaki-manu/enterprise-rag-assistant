"""Generates or updates app/eval/results/grading_sheet.csv from answer files.

Reads app/eval/results/answers_<variant>.json files (any that exist) and the golden file.
Writes app/eval/results/grading_sheet.csv with columns:
  question_id, category, style, answerable, variant, answer, verification_status,
  refused, reference_answer, grade, notes

Rules:
- The reference_answer is copied for the grader's convenience.
- The script must NOT fill grade or notes (leaves them empty).
- If grading_sheet.csv already exists, keep existing grade and notes values for matching
  (question_id, variant) rows and only add new rows.
- Handles missing variant files gracefully.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from app.agents.synthesizer import NO_EVIDENCE_ANSWER
except ImportError:
    NO_EVIDENCE_ANSWER = "I don't have sufficient evidence in the provided documents."

LOGGER = logging.getLogger("make_grading_sheet")

COLUMNS = [
    "question_id",
    "category",
    "style",
    "answerable",
    "variant",
    "answer",
    "verification_status",
    "refused",
    "reference_answer",
    "grade",
    "notes",
]

DEFAULT_GOLDEN_PATH = Path("app/eval/golden_questions.json")
DEFAULT_RESULTS_DIR = Path("app/eval/results")
DEFAULT_OUTPUT_CSV = Path("app/eval/results/grading_sheet.csv")


def load_golden_questions(golden_path: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Loads golden questions mapping question_id -> metadata and preserves question order."""
    if not golden_path.exists():
        LOGGER.warning("Golden file not found: %s", golden_path)
        return {}, []

    raw = json.loads(golden_path.read_text(encoding="utf-8"))
    order: list[str] = []
    golden_map: dict[str, dict[str, Any]] = {}

    for item in raw:
        qid = item["question_id"]
        order.append(qid)
        cat = item.get("category", "")
        style = item.get("style", "")
        ans = item.get("answerable")
        if ans is None:
            ans = (cat != "unanswerable")
        ref_ans = item.get("reference_answer", "") or ""
        golden_map[qid] = {
            "question_id": qid,
            "category": cat,
            "style": style,
            "answerable": bool(ans),
            "reference_answer": ref_ans,
        }

    return golden_map, order


def extract_variant_from_path(file_path: Path) -> str:
    """Extracts variant name from filename like answers_<variant>.json."""
    match = re.match(r"^answers_(.+)\.json$", file_path.name, re.IGNORECASE)
    if match:
        return match.group(1)
    if file_path.stem.startswith("answers_"):
        return file_path.stem[8:]
    return file_path.stem


def parse_answer_file(file_path: Path, variant_name: str | None = None) -> list[dict[str, Any]]:
    """Reads an answers file and returns a list of answer records.

    Handles missing files gracefully by logging a warning and returning an empty list.
    Supports:
    - Top-level list of answer objects
    - Dict with a 'results' or 'answers' list
    - Dict mapping question_id -> answer object
    """
    if not file_path.exists():
        LOGGER.warning("Answer file does not exist: %s", file_path)
        return []

    try:
        content = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as exc:
        LOGGER.warning("Failed to parse JSON from %s: %s", file_path, exc)
        return []

    default_variant = variant_name or extract_variant_from_path(file_path)
    items: list[dict[str, Any]] = []

    if isinstance(content, list):
        items = [x for x in content if isinstance(x, dict)]
    elif isinstance(content, dict):
        if "results" in content and isinstance(content["results"], list):
            items = [x for x in content["results"] if isinstance(x, dict)]
            if "variant" in content and not variant_name:
                default_variant = str(content["variant"])
        elif "answers" in content and isinstance(content["answers"], list):
            items = [x for x in content["answers"] if isinstance(x, dict)]
            if "variant" in content and not variant_name:
                default_variant = str(content["variant"])
        else:
            for k, v in content.items():
                if isinstance(v, dict):
                    rec = dict(v)
                    rec.setdefault("question_id", k)
                    items.append(rec)

    records: list[dict[str, Any]] = []
    for item in items:
        qid = item.get("question_id")
        if not qid:
            continue

        # Skip any record whose error is not null, so error answers never enter the sheet
        error_val = item.get("error")
        if error_val is None and isinstance(item.get("response"), dict):
            error_val = item["response"].get("error")
        if error_val is not None:
            continue

        resp = item.get("response")
        if isinstance(resp, dict):
            answer_text = resp.get("answer", "")
            ver_status = resp.get("verification_status", "")
            resp_refused = resp.get("refused")
        else:
            answer_text = item.get("answer", "")
            ver_status = item.get("verification_status", "")
            resp_refused = None

        if "refused" in item:
            refused = bool(item["refused"])
        elif resp_refused is not None:
            refused = bool(resp_refused)
        else:
            norm_ans = str(answer_text).strip()
            refused = bool(
                norm_ans == NO_EVIDENCE_ANSWER
                or NO_EVIDENCE_ANSWER.lower() in norm_ans.lower()
            )

        var = item.get("variant") or default_variant

        records.append({
            "question_id": str(qid),
            "variant": str(var),
            "answer": str(answer_text),
            "verification_status": str(ver_status),
            "refused": bool(refused),
        })

    return records


def load_existing_grading_sheet(csv_path: Path) -> dict[tuple[str, str], dict[str, str]]:
    """Reads existing CSV and maps (question_id, variant) -> dict of row values."""
    if not csv_path.exists():
        return {}

    existing: dict[tuple[str, str], dict[str, str]] = {}
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                qid = row.get("question_id", "").strip()
                var = row.get("variant", "").strip()
                if qid and var:
                    existing[(qid, var)] = row
    except Exception as exc:
        LOGGER.warning("Could not read existing sheet %s: %s", csv_path, exc)
    return existing


def build_grading_rows(
    golden_map: dict[str, dict[str, Any]],
    golden_order: list[str],
    all_answers: list[dict[str, Any]],
    existing_sheet: dict[tuple[str, str], dict[str, str]],
) -> list[dict[str, Any]]:
    """Merges golden question metadata with answers while preserving existing manual grades."""
    variants: list[str] = []
    answers_by_key: dict[tuple[str, str], dict[str, Any]] = {}

    for ans in all_answers:
        v = ans["variant"]
        if v not in variants:
            variants.append(v)
        answers_by_key[(ans["question_id"], v)] = ans

    # Include any variants already present in the existing CSV
    for (_, v) in existing_sheet:
        if v not in variants:
            variants.append(v)

    rows: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    for v in variants:
        # First process questions in golden order
        for qid in golden_order:
            key = (qid, v)
            existing_row = existing_sheet.get(key, {})
            has_grade = bool(existing_row.get("grade", "").strip())
            if key in answers_by_key or has_grade:
                seen_keys.add(key)
                g_meta = golden_map.get(qid, {})
                ans_data = answers_by_key.get(key, {})

                cat = g_meta.get("category") or existing_row.get("category", "")
                style = g_meta.get("style") or existing_row.get("style", "")
                ans_bool = g_meta.get("answerable")
                if ans_bool is None:
                    ans_bool = existing_row.get("answerable", "True") in ("True", "true", True)
                ref_ans = g_meta.get("reference_answer", "") or existing_row.get("reference_answer", "")

                answer_val = ans_data.get("answer") if "answer" in ans_data else existing_row.get("answer", "")
                ver_val = ans_data.get("verification_status") if "verification_status" in ans_data else existing_row.get("verification_status", "")
                refused_val = ans_data.get("refused") if "refused" in ans_data else (existing_row.get("refused", "False") in ("True", "true", True))

                # Preserved grade and notes: NEVER fill if new
                preserved_grade = existing_row.get("grade", "")
                preserved_notes = existing_row.get("notes", "")

                rows.append({
                    "question_id": qid,
                    "category": cat,
                    "style": style,
                    "answerable": bool(ans_bool),
                    "variant": v,
                    "answer": answer_val,
                    "verification_status": ver_val,
                    "refused": bool(refused_val),
                    "reference_answer": ref_ans,
                    "grade": preserved_grade,
                    "notes": preserved_notes,
                })

        # Process any questions for this variant not in golden_order
        for (qid, var), ans_data in answers_by_key.items():
            if var == v and (qid, var) not in seen_keys:
                seen_keys.add((qid, var))
                g_meta = golden_map.get(qid, {})
                existing_row = existing_sheet.get((qid, var), {})
                cat = g_meta.get("category") or existing_row.get("category", "")
                style = g_meta.get("style") or existing_row.get("style", "")
                ans_bool = g_meta.get("answerable", True)
                ref_ans = g_meta.get("reference_answer", "") or existing_row.get("reference_answer", "")

                rows.append({
                    "question_id": qid,
                    "category": cat,
                    "style": style,
                    "answerable": bool(ans_bool),
                    "variant": var,
                    "answer": ans_data.get("answer", ""),
                    "verification_status": ans_data.get("verification_status", ""),
                    "refused": bool(ans_data.get("refused", False)),
                    "reference_answer": ref_ans,
                    "grade": existing_row.get("grade", ""),
                    "notes": existing_row.get("notes", ""),
                })

    # Any remaining rows in existing sheet that were not matched (keep only if already graded)
    for (qid, var), ex_row in existing_sheet.items():
        if (qid, var) not in seen_keys:
            if not ex_row.get("grade", "").strip():
                continue
            seen_keys.add((qid, var))
            rows.append({
                "question_id": qid,
                "category": ex_row.get("category", ""),
                "style": ex_row.get("style", ""),
                "answerable": ex_row.get("answerable", "True") in ("True", "true", True),
                "variant": var,
                "answer": ex_row.get("answer", ""),
                "verification_status": ex_row.get("verification_status", ""),
                "refused": ex_row.get("refused", "False") in ("True", "true", True),
                "reference_answer": ex_row.get("reference_answer", ""),
                "grade": ex_row.get("grade", ""),
                "notes": ex_row.get("notes", ""),
            })

    return rows


def write_grading_sheet(rows: list[dict[str, Any]], output_path: Path) -> None:
    """Writes the rows to output CSV file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for r in rows:
            row_dict = {
                "question_id": r.get("question_id", ""),
                "category": r.get("category", ""),
                "style": r.get("style", ""),
                "answerable": str(bool(r.get("answerable", True))),
                "variant": r.get("variant", ""),
                "answer": r.get("answer", ""),
                "verification_status": r.get("verification_status", ""),
                "refused": str(bool(r.get("refused", False))),
                "reference_answer": r.get("reference_answer", ""),
                "grade": r.get("grade") or "",
                "notes": r.get("notes") or "",
            }
            writer.writerow(row_dict)


def make_grading_sheet(
    golden_path: Path = DEFAULT_GOLDEN_PATH,
    results_dir: Path = DEFAULT_RESULTS_DIR,
    output_csv: Path = DEFAULT_OUTPUT_CSV,
    variant_files: list[Path] | None = None,
) -> Path:
    """Main workflow to generate or update grading_sheet.csv.

    - Reads golden questions.
    - Discovers answers_<variant>.json files or uses provided variant_files.
    - Handles missing files gracefully.
    - Preserves existing grade and notes for matching (question_id, variant) rows.
    - Never fills grade or notes for new rows.
    """
    golden_map, golden_order = load_golden_questions(golden_path)

    files_to_read: list[Path] = []
    if variant_files:
        files_to_read = list(variant_files)
    elif results_dir.exists():
        files_to_read = sorted(results_dir.glob("answers_*.json"))

    all_answers: list[dict[str, Any]] = []
    for f in files_to_read:
        if not f.exists():
            LOGGER.warning("Variant file not found, skipping: %s", f)
            continue
        parsed = parse_answer_file(f)
        all_answers.extend(parsed)

    existing_sheet = load_existing_grading_sheet(output_csv)

    rows = build_grading_rows(
        golden_map=golden_map,
        golden_order=golden_order,
        all_answers=all_answers,
        existing_sheet=existing_sheet,
    )

    write_grading_sheet(rows, output_csv)
    LOGGER.info("Wrote %d rows to %s", len(rows), output_csv)
    return output_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate or update grading_sheet.csv from answers_<variant>.json files."
    )
    parser.add_argument(
        "--golden-file",
        type=Path,
        default=DEFAULT_GOLDEN_PATH,
        help="Path to golden questions JSON (default: app/eval/golden_questions.json)",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help="Directory containing answers_<variant>.json files (default: app/eval/results)",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=DEFAULT_OUTPUT_CSV,
        help="Path to output grading_sheet.csv (default: app/eval/results/grading_sheet.csv)",
    )
    parser.add_argument(
        "--variant-files",
        type=Path,
        nargs="*",
        default=None,
        help="Specific answers_<variant>.json files to process",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    out_file = make_grading_sheet(
        golden_path=args.golden_file,
        results_dir=args.results_dir,
        output_csv=args.output_csv,
        variant_files=args.variant_files,
    )
    print(f"Grading sheet written to {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
