import json
import sys
import uuid
from pathlib import Path

from app.ingestion.pipeline import ingest_document
from app.retrieval.factory import build_default_retriever
from app.schemas.retrieval import RetrievalRequest

sys.stdout.reconfigure(encoding="utf-8")

PDF_PATH = "data/eval/documents/tcs_annual_report.pdf"
LABELS_PATH = Path("data/eval/golden_labels.json")
WATCH = ["tcs-gold-05", "tcs-gold-07", "tcs-gold-10"]


def main() -> int:
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    result = ingest_document(PDF_PATH)
    if len(result.chunks) != labels["chunk_count"]:
        print(f"STOP: {len(result.chunks)} chunks now, labels were made on {labels['chunk_count']}")
        return 1
    number = {c.chunk_id: i for i, c in enumerate(result.chunks)}

    retriever = build_default_retriever(collection_name=f"diag_{uuid.uuid4().hex}")
    retriever.index_chunks(result.chunks)

    for q in labels["questions"]:
        if q["question_id"] not in WATCH:
            continue
        wanted = set()
        for need in q["needs"]:
            wanted.update(need["chunk_ids"])
        print(f"\n{q['question_id']}: {q['question']}")
        print("labelled chunks:", sorted(number[c] for c in wanted))
        response = retriever.retrieve(RetrievalRequest(query=q["question"], top_k=10))
        for pos, r in enumerate(response.results, 1):
            mark = "LABEL" if r.chunk_id in wanted else ""
            text = r.text.replace("\n", " ")[:90]
            print(f"{pos:>3} #{number[r.chunk_id]:<4} p.{r.page_number} {r.dense_score:.3f} {mark:<6} {text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())