import json
import sys
from pathlib import Path

from app.ingestion.parsers.pdf_parser import parse_pdf
from app.ingestion.pipeline import ingest_document
from app.ingestion.table_format import linearize_table
from scripts.resolve_labels import find_matches, norm

sys.stdout.reconfigure(encoding="utf-8")

PDF_PATH = "data/eval/documents/tcs_annual_report.pdf"
QUESTIONS_PATH = Path("data/eval/retrieval_questions.json")
APPLY = "--apply" in sys.argv


def main() -> None:
    raw = parse_pdf(PDF_PATH).chunks                # tables still in pipe form
    converted = ingest_document(PDF_PATH).chunks    # tables as sentences (what retrieval sees)
    raw_indexed = [(i, c, norm(c.text)) for i, c in enumerate(raw)]
    new_indexed = [(i, c, norm(c.text)) for i, c in enumerate(converted)]

    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    changes, problems = 0, 0

    for q in questions:
        for field in ("evidence", "alt_evidence"):
            for index, phrase in enumerate(q.get(field, [])):
                if "|" not in phrase:
                    continue
                print(f"{q['question_id']} {field}[{index}]")
                print(f"   old: {phrase}")

                matches = find_matches(phrase, raw_indexed)
                if not matches:
                    print("   no unconverted chunk contains this phrase: check its wording\n")
                    problems += 1
                    continue

                chunk = matches[0][1]
                lines = [line.strip() for line in chunk.text.split("\n") if line.strip()]
                table_lines = [line for line in lines if "|" in line]
                target = norm(phrase)
                row = next((line for line in table_lines[1:] if target in norm(line)), None)
                if row is None:
                    print("   the phrase is not inside a single table row: write this one by hand\n")
                    problems += 1
                    continue

                sentence = linearize_table(table_lines[0] + "\n" + row).rstrip(".")
                found = find_matches(sentence, new_indexed)
                print(f"   new: {sentence}")
                if found:
                    where = ", ".join(f"#{i} (p.{c.metadata.page_number})" for i, c in found)
                    print(f"   check: appears in {len(found)} converted chunk(s): {where}\n")
                    if APPLY:
                        q[field][index] = sentence
                        changes += 1
                else:
                    print("   check: NOT found in the converted text, left unchanged\n")
                    problems += 1

    if APPLY:
        QUESTIONS_PATH.write_text(json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{changes} phrase(s) rewritten in {QUESTIONS_PATH}. Review with: git diff {QUESTIONS_PATH}")
    else:
        print("Dry run only. Nothing was changed. Run again with --apply to rewrite the file.")
    if problems:
        print(f"{problems} phrase(s) need attention (listed above).")


if __name__ == "__main__":
    main()