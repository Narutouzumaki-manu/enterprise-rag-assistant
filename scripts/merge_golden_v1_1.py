import json
import sys
from pathlib import Path
from typing import Any

from app.eval.golden_schema import validate_golden_questions

# Ensure stdout encodes UTF-8 safely on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CANONICAL_PATH = Path("app/eval/golden_questions.json")
PATCH_PATH = Path("data/eval/golden_patch_v1_1.json")
OVERLAP_PATH = Path("app/eval/golden_tuned_overlap.json")
RETRIEVAL_LABELS_PATH = Path("data/eval/retrieval_labels.json")
PDF_PATH = Path("data/eval/documents/tcs_annual_report.pdf")


def compute_shared_chunks(
    golden_questions: list[dict[str, Any]],
    retrieval_labels_path: Path = RETRIEVAL_LABELS_PATH,
    pdf_path: Path = PDF_PATH,
    chunks: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Compute shared chunk IDs between evidence-matched golden chunks and tuned question chunks."""
    from app.eval.golden_schema import GoldenQuestion
    from app.eval.validate_golden import load_chunks, validate_question_phrases

    if chunks is None:
        chunks = load_chunks(str(pdf_path))

    labels_data = json.loads(retrieval_labels_path.read_text(encoding="utf-8"))
    tuned_chunks: dict[str, set[str]] = {}
    for q in labels_data.get("questions", []):
        cids: set[str] = set()
        for need in q.get("needs", []):
            for cid in need.get("chunk_ids", []):
                cids.add(cid)
        tuned_chunks[q["question_id"]] = cids

    shared_chunk_entries: list[dict[str, Any]] = []

    for item in golden_questions:
        gq = GoldenQuestion(**item)
        res = validate_question_phrases(gq, chunks)
        gcids = set(res.unique_matched_chunk_ids)

        for rid, rcids in sorted(tuned_chunks.items()):
            intersect = gcids.intersection(rcids)
            if intersect:
                shared_chunk_entries.append({
                    "golden": gq.question_id,
                    "tuned": rid,
                    "shared_chunk_ids": sorted(list(intersect)),
                })

    return shared_chunk_entries


def generate_overlap_file(
    golden_questions: list[dict[str, Any]],
    output_path: Path = OVERLAP_PATH,
    retrieval_labels_path: Path = RETRIEVAL_LABELS_PATH,
    pdf_path: Path = PDF_PATH,
    chunks: list[Any] | None = None,
) -> dict[str, Any]:
    """Generate golden_tuned_overlap.json with computed shared_chunk list."""
    shared_chunks = compute_shared_chunks(
        golden_questions,
        retrieval_labels_path=retrieval_labels_path,
        pdf_path=pdf_path,
        chunks=chunks,
    )

    overlap_data: dict[str, Any] = {
        "tuned_pool": "data/eval/retrieval_questions.json (q01-q20; q17, q18, q20 unanswerable)",
        "flagged_same_fact": [
            {"golden": "tcs-gold-04", "tuned": "q16"},
            {"golden": "tcs-gold-14", "tuned": "q02"},
            {"golden": "tcs-gold-16", "tuned": "q08"},
            {"golden": "tcs-gold-21", "tuned": "q15"},
        ],
        "shared_chunk": shared_chunks,
    }

    output_path.write_text(
        json.dumps(overlap_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Computed overlap file written to '{output_path}' ({len(shared_chunks)} shared-chunk relationships).")
    return overlap_data


def merge_golden_v1_1(
    canonical_file: Path = CANONICAL_PATH,
    patch_file: Path = PATCH_PATH,
    output_file: Path | None = None,
    overlap_output_file: Path | None = OVERLAP_PATH,
    generate_overlap: bool = True,
    chunks: list[Any] | None = None,
) -> bool:
    """
    Apply patch v1.1 to the canonical golden questions file.
    - refuses if tcs-gold-32/33/34 already exist (no double apply);
    - replace: ids must exist, swap the whole entry;
    - append: ids must NOT exist;
    - validates every item with GoldenQuestion;
    - writes UTF-8, ensure_ascii=False, indent=2;
    - prints old and new question text of each replaced id;
    - computes app/eval/golden_tuned_overlap.json from data.
    """
    if output_file is None:
        output_file = canonical_file

    if not canonical_file.exists():
        raise FileNotFoundError(f"Canonical golden file not found: {canonical_file}")
    if not patch_file.exists():
        raise FileNotFoundError(f"Patch file not found: {patch_file}")

    canonical_data: list[dict[str, Any]] = json.loads(canonical_file.read_text(encoding="utf-8"))
    patch_data: dict[str, list[dict[str, Any]]] = json.loads(patch_file.read_text(encoding="utf-8"))

    replace_items = patch_data.get("replace", [])
    append_items = patch_data.get("append", [])

    # Map existing questions by id and index
    canonical_indices: dict[str, int] = {}
    for idx, q in enumerate(canonical_data):
        qid = q.get("question_id")
        if not qid:
            raise ValueError("Item in canonical file missing 'question_id'")
        if qid in canonical_indices:
            raise ValueError(f"Duplicate question_id in canonical file: '{qid}'")
        canonical_indices[qid] = idx

    # Check for double apply refusal (specifically tcs-gold-32, tcs-gold-33, tcs-gold-34)
    target_double_apply = {"tcs-gold-32", "tcs-gold-33", "tcs-gold-34"}
    already_appended = target_double_apply.intersection(canonical_indices.keys())
    if already_appended:
        print(
            f"Refusing merge: Canonical file already contains {sorted(already_appended)} (no double apply)."
        )
        return False

    # 1. Replace: ids must exist, swap the whole entry, print old and new text
    replaced_count = 0
    working_data = list(canonical_data)
    for rep in replace_items:
        qid = rep.get("question_id")
        if not qid:
            raise ValueError("Replace item missing 'question_id'")
        if qid not in canonical_indices:
            raise ValueError(f"Replace question_id '{qid}' not found in canonical questions")

        idx = canonical_indices[qid]
        old_item = working_data[idx]
        old_text = old_item.get("question", "")
        new_text = rep.get("question", "")

        print(f"Replaced {qid}:")
        print(f"  OLD: \"{old_text}\"")
        print(f"  NEW: \"{new_text}\"")

        working_data[idx] = rep
        replaced_count += 1

    # 2. Append: ids must NOT exist
    for app in append_items:
        qid = app.get("question_id")
        if not qid:
            raise ValueError("Append item missing 'question_id'")
        if qid in canonical_indices:
            raise ValueError(f"Append question_id '{qid}' already exists in canonical questions")
        working_data.append(app)

    # 3. Validate every item with GoldenQuestion and check unique IDs
    validated = validate_golden_questions(working_data)

    # 4. Write canonical output file
    output_file.write_text(
        json.dumps([q.model_dump() for q in validated], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\nSuccessfully applied patch v1.1 into '{output_file}':")
    print(f"  - Questions replaced : {replaced_count}")
    print(f"  - Questions appended : {len(append_items)}")
    print(f"  - New total questions: {len(validated)}")

    # 5. Generate golden_tuned_overlap.json if requested
    if generate_overlap and overlap_output_file:
        raw_validated = [q.model_dump() for q in validated]
        generate_overlap_file(
            raw_validated,
            output_path=overlap_output_file,
            chunks=chunks,
        )

    return True


def main() -> int:
    try:
        merge_golden_v1_1()
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
