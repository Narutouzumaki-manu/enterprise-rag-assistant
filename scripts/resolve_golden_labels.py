import json
import re
import sys
from pathlib import Path

from app.ingestion.pipeline import ingest_document

sys.stdout.reconfigure(encoding="utf-8")  # the rupee sign must print safely on Windows

PDF_PATH = "data/eval/documents/tcs_annual_report.pdf"
QUESTIONS_PATH = Path("data/eval/tcs_golden_questions_deduplicated.json")
LABELS_PATH = Path("data/eval/golden_labels.json")


def norm(text: str) -> str:
    """Make text comparable: unify quotes and spaces, drop soft hyphens, lowercase."""
    text = (
        text.replace("\u2019", "'").replace("\u2018", "'")
        .replace("\u201c", '"').replace("\u201d", '"')
        .replace("\u00a0", " ").replace("\u00ad", "")
    )
    return re.sub(r"\s+", " ", text).strip().lower()


def find_matches(phrase: str, indexed: list) -> list:
    target = norm(phrase)
    return [(i, chunk) for i, chunk, normalized in indexed if target in normalized]


def describe(matches: list) -> str:
    if not matches:
        return "NOT FOUND"
    parts = []
    for i, chunk in matches:
        start = chunk.text.strip().replace("\n", " ")[:70]
        parts.append(f'#{i} (p.{chunk.metadata.page_number}) "{start}..."')
    return f"{len(matches)} chunk(s): " + " | ".join(parts)


def main() -> int:
    result = ingest_document(PDF_PATH)
    if not result.chunks:
        print("Ingestion problem:", result.status, result.error_message)
        return 1
    indexed = [(i, c, norm(c.text)) for i, c in enumerate(result.chunks)]
    print(f"{len(result.chunks)} chunks from {result.document_id}\n")

    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    labelled = []
    problems = 0

    for q in questions:
        evidence = q.get("evidence", [])
        alt = q.get("alt_evidence", [])
        print(f"{q['question_id']} [{q['category']}/{q['style']}] {q['question'][:70]}")

        if not evidence:
            print("   no evidence (unanswerable): nothing to resolve\n")
            labelled.append({
                "question_id": q["question_id"], "question": q["question"],
                "category": q["category"], "style": q["style"], "needs": [],
            })
            continue

        if len(evidence) > 1 and alt:
            problems += 1
            print("   PROBLEM: several evidence phrases AND alt_evidence. Move alt phrases into")
            print("   evidence or empty alt_evidence (see the q02 note). Skipping this question.\n")
            continue

        needs = []
        for phrase in evidence:
            matches = find_matches(phrase, indexed)
            print(f"   evidence: {describe(matches)}")
            if not matches:
                problems += 1
            needs.append({"phrase": phrase, "chunk_ids": [c.chunk_id for _, c in matches]})

        for phrase in alt:
            matches = find_matches(phrase, indexed)
            print(f"   alt     : {describe(matches)}")
            if not matches:
                problems += 1
            for _, c in matches:
                if c.chunk_id not in needs[0]["chunk_ids"]:
                    needs[0]["chunk_ids"].append(c.chunk_id)
        print()

        labelled.append({
            "question_id": q["question_id"], "question": q["question"],
            "category": q["category"], "style": q["style"], "needs": needs,
        })

    scorable = sum(1 for item in labelled if item["needs"])
    print(f"{len(questions)} questions | {scorable} scorable | {problems} problem(s)")

    if problems:
        print("Fix the problems above, then run again. Labels file NOT written.")
        return 1

    LABELS_PATH.write_text(
        json.dumps(
            {"document_id": result.document_id, "chunk_count": len(result.chunks), "questions": labelled},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print("written to", LABELS_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())