import json
import sys
from pathlib import Path
from typing import Any

from app.eval.golden_schema import validate_golden_questions

# Ensure stdout encodes UTF-8 safely on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CANONICAL_PATH = Path("app/eval/golden_questions.json")
PATCH_PATH = Path("data/eval/golden_patch_evidence.json")
NEW_ANSWERABLE_PATH = Path("data/eval/golden_new_answerable.json")
NEW_UNANSWERABLE_PATH = Path("data/eval/golden_new_unanswerable.json")


def merge_golden(
    canonical_file: Path = CANONICAL_PATH,
    patch_file: Path = PATCH_PATH,
    new_ans_file: Path = NEW_ANSWERABLE_PATH,
    new_unans_file: Path = NEW_UNANSWERABLE_PATH,
    output_file: Path | None = None,
) -> bool:
    """
    Merge golden patches and new questions into the canonical file.
    Safe to re-run: refuses if new IDs are already present in the canonical file.
    """
    if output_file is None:
        output_file = canonical_file

    if not canonical_file.exists():
        raise FileNotFoundError(f"Canonical golden file not found: {canonical_file}")
    if not patch_file.exists():
        raise FileNotFoundError(f"Patch file not found: {patch_file}")
    if not new_ans_file.exists():
        raise FileNotFoundError(f"New answerable file not found: {new_ans_file}")
    if not new_unans_file.exists():
        raise FileNotFoundError(f"New unanswerable file not found: {new_unans_file}")

    canonical_data: list[dict[str, Any]] = json.loads(canonical_file.read_text(encoding="utf-8"))
    patch_data: list[dict[str, Any]] = json.loads(patch_file.read_text(encoding="utf-8"))
    new_ans_data: list[dict[str, Any]] = json.loads(new_ans_file.read_text(encoding="utf-8"))
    new_unans_data: list[dict[str, Any]] = json.loads(new_unans_file.read_text(encoding="utf-8"))

    # Map existing questions by id
    canonical_by_id: dict[str, dict[str, Any]] = {}
    for q in canonical_data:
        qid = q.get("question_id")
        if not qid:
            raise ValueError("Item in canonical file missing 'question_id'")
        if qid in canonical_by_id:
            raise ValueError(f"Duplicate question_id in canonical file: '{qid}'")
        canonical_by_id[qid] = q

    # Check for new ids to append
    new_items = list(new_ans_data) + list(new_unans_data)
    new_ids: list[str] = []
    seen_new_ids: set[str] = set()
    for item in new_items:
        qid = item.get("question_id")
        if not qid:
            raise ValueError("New question item missing 'question_id'")
        if qid in seen_new_ids:
            raise ValueError(f"Duplicate question_id across new questions: '{qid}'")
        seen_new_ids.add(qid)
        new_ids.append(qid)

    # Check for double append refusal
    already_present = set(canonical_by_id.keys()).intersection(seen_new_ids)
    if already_present:
        print(
            f"Refusing merge: Canonical file already contains new question IDs {sorted(already_present)} (no double append)."
        )
        return False

    # a) Apply patches: replace ONLY evidence and alt_evidence, assert no other field changed
    patched_count = 0
    for patch in patch_data:
        qid = patch.get("question_id")
        if not qid:
            raise ValueError("Patch item missing 'question_id'")
        if qid not in canonical_by_id:
            raise ValueError(f"Patch question_id '{qid}' not found in canonical questions")

        target = canonical_by_id[qid]

        # Verify no non-evidence fields in patch conflict with canonical
        for key, val in patch.items():
            if key not in ("question_id", "evidence", "alt_evidence"):
                canonical_val = target.get(key)
                if canonical_val != val:
                    raise AssertionError(
                        f"Patch tried to change non-evidence field '{key}' on {qid}: "
                        f"canonical={canonical_val!r}, patch={val!r}"
                    )

        # Snapshot non-evidence fields before update
        non_evidence_before = {k: v for k, v in target.items() if k not in ("evidence", "alt_evidence")}

        # Replace ONLY evidence and alt_evidence
        target["evidence"] = list(patch.get("evidence", []))
        target["alt_evidence"] = list(patch.get("alt_evidence", []))

        # Assert no other field changed
        non_evidence_after = {k: v for k, v in target.items() if k not in ("evidence", "alt_evidence")}
        assert non_evidence_before == non_evidence_after, f"Non-evidence fields altered for question '{qid}'"
        patched_count += 1

    # b) Append new questions in file order
    merged_list = list(canonical_data) + new_items

    # c) Validate every item with GoldenQuestion and check unique IDs
    validated = validate_golden_questions(merged_list)

    # d) Write output file
    output_file.write_text(
        json.dumps([q.model_dump() for q in validated], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Successfully merged golden questions into '{output_file}':")
    print(f"  - Questions patched : {patched_count}")
    print(f"  - Questions appended: {len(new_items)}")
    print(f"  - New total         : {len(validated)}")
    return True


def main() -> int:
    try:
        merge_golden()
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
