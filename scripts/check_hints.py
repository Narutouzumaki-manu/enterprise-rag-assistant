"""Retrieval only, no LLM requests: where does q19's right chunk rank for each search string?"""
import sys
import uuid

from app.retrieval.factory import build_default_retriever
from app.schemas.retrieval import RetrievalRequest
from scripts.run_comparison import load_labels_and_chunks

sys.stdout.reconfigure(encoding="utf-8")

SEARCHES = [
    "What was the company's profit after tax in the October-to-December quarter of the year before FY26?",
    "TCS Q3 FY25 profit after tax",
    "TCS profit after tax Q3 FY25 October December 2024",
    "TCS Q3 FY25 profit after tax October\u2011December 2024",  # exactly as the model wrote it
    "TCS Q3 FY25 profit after tax October-December 2024",       # same with a plain hyphen
    "Net income Q3 FY25",
    "TCS net income Q3 FY25 October December 2024",
]

labels, chunks = load_labels_and_chunks()
q19 = next(q for q in labels["questions"] if q["question_id"] == "q19")
wanted = set().union(*[set(need["chunk_ids"]) for need in q19["needs"]])

retriever = build_default_retriever(collection_name=f"hints_{uuid.uuid4().hex}")
retriever.index_chunks(chunks)

print("rank of q19's right chunk (search returns up to 30)")
for text in SEARCHES:
    results = retriever.retrieve(RetrievalRequest(query=text, top_k=30)).results
    rank = next((i for i, r in enumerate(results, 1) if r.chunk_id in wanted), None)
    label = f"rank {rank}" if rank else "not in 30"
    print(f"{label:>12} | {text}")