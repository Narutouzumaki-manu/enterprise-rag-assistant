import sys
import uuid

from app.retrieval.bm25_index import BM25Index
from app.retrieval.embeddings import EmbeddingService
from app.retrieval.hybrid_search import HybridRetriever
from app.retrieval.metrics import mean, score_against_needs
from app.retrieval.reranker import Reranker
from app.retrieval.vector_store import VectorStore
from app.schemas.retrieval import RetrievalRequest
from scripts.run_comparison import load_labels_and_chunks

sys.stdout.reconfigure(encoding="utf-8")

TOP_K = 10
METRICS = ["recall@5", "recall@10", "mrr", "ndcg@10"]
SETUPS = ["Meaning only", "Keyword only", "Hybrid + rerank"]
TABLE_QUESTIONS = ["q12", "q13", "q14", "q19"]


def looks_like_table(text):
    return sum(1 for line in text.split("\n") if "|" in line) >= 2


def linearize_table(text):
    """Turn pipe-separated rows into short sentences: 'Header: value; Header: value.'"""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    table_lines = [line for line in lines if "|" in line]
    other_lines = [line for line in lines if "|" not in line]
    header = [cell.strip() for cell in table_lines[0].split("|")]
    sentences = []
    for line in table_lines[1:]:
        cells = [cell.strip() for cell in line.split("|")]
        parts = []
        for index, cell in enumerate(cells):
            if not cell:
                continue
            head = header[index] if index < len(header) else ""
            parts.append(f"{head}: {cell}" if head else cell)
        if parts:
            sentences.append("; ".join(parts) + ".")
    return " ".join(other_lines + sentences)


def evaluate(chunk_list, labels, embedding, reranker):
    store = VectorStore(embedding, collection_name=f"tbl_{uuid.uuid4().hex}")
    bm25 = BM25Index()
    full = HybridRetriever(store, bm25, reranker, fetch_k=30)
    full.index_chunks(chunk_list)
    searchers = {
        "Meaning only": lambda q: store.search(q, k=TOP_K),
        "Keyword only": lambda q: bm25.search(q, k=TOP_K),
        "Hybrid + rerank": lambda q: full.retrieve(RetrievalRequest(query=q, top_k=TOP_K)).results,
    }
    rows = []
    for q in labels["questions"]:
        if not q["needs"]:
            continue
        needs = [set(n["chunk_ids"]) for n in q["needs"]]
        wanted = set().union(*needs)
        for setup, search in searchers.items():
            ranked = [r.chunk_id for r in search(q["question"])]
            first = next((pos for pos, cid in enumerate(ranked, 1) if cid in wanted), None)
            rows.append({
                "qid": q["question_id"], "category": q["category"], "setup": setup,
                "scores": score_against_needs(ranked, needs), "first": first,
            })
    return rows


def show(variant, rows):
    print(f"--- {variant} ---")
    groups = (
        ("ALL 17 scorable questions", rows),
        ("TABLE questions (q12, q13, q14, q19)", [r for r in rows if r["category"] == "table"]),
    )
    for title, selected in groups:
        print(title)
        print(f"{'':<18}" + "".join(f"{m:>11}" for m in METRICS))
        for setup in SETUPS:
            subset = [r for r in selected if r["setup"] == setup]
            values = [mean(r["scores"][m] for r in subset) for m in METRICS]
            print(f"{setup:<18}" + "".join(f"{v:>11.3f}" for v in values))
        print()
    print("Where the right chunk landed (position in the top 10, '-' = missed):")
    print(f"{'q':<6}" + "".join(f"{s:>18}" for s in SETUPS))
    for qid in TABLE_QUESTIONS:
        cells = []
        for setup in SETUPS:
            r = next(x for x in rows if x["qid"] == qid and x["setup"] == setup)
            cells.append("-" if r["first"] is None else str(r["first"]))
        print(f"{qid:<6}" + "".join(f"{c:>18}" for c in cells))
    print()


def main() -> None:
    labels, chunks = load_labels_and_chunks()
    converted = [
        c.model_copy(update={"text": linearize_table(c.text)}) if looks_like_table(c.text) else c
        for c in chunks
    ]
    n_tables = sum(1 for c in chunks if looks_like_table(c.text))
    print(f"{n_tables} of {len(chunks)} chunks look like tables and were rewritten as sentences.\n")

    q12 = next(q for q in labels["questions"] if q["question_id"] == "q12")
    example_id = q12["needs"][0]["chunk_ids"][0]
    before = next(c for c in chunks if c.chunk_id == example_id)
    after = next(c for c in converted if c.chunk_id == example_id)
    print("EXAMPLE (the chunk for q12)")
    print("before:", before.text[:300].replace("\n", " / "))
    print("after :", after.text[:300])
    print()

    embedding = EmbeddingService()
    reranker = Reranker()
    show("ORIGINAL table text", evaluate(chunks, labels, embedding, reranker))
    show("TABLES AS SENTENCES", evaluate(converted, labels, embedding, reranker))


if __name__ == "__main__":
    main()