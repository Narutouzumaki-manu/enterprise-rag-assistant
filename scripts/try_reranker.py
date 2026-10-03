from app.retrieval.reranker import Reranker
from app.schemas.retrieval import RetrievedChunk


def rc(chunk_id, text):
    return RetrievedChunk(chunk_id=chunk_id, document_id="d", text=text)


def fmt(value, places):
    return "  -  " if value is None else f"{value:.{places}f}"


query = "How do I reset my account password?"

# Deliberately shuffled: the best answer (B) starts in the middle.
candidates = [
    rc("A", "Our office is closed on public holidays and weekends."),
    rc("B", "To reset your password, open Settings > Security and click 'Forgot password'."),
    rc("C", "Account passwords must contain at least 12 characters."),
    rc("D", "The quarterly report shows a 12% increase in revenue."),
    rc("E", "Passwords can be changed from the profile page after you sign in."),
]

reranker = Reranker()
ranked = reranker.rerank(query, candidates)

print(f"Query: {query}\n")
print("rank  chunk  rerank   text")
for i, c in enumerate(ranked, start=1):
    print(f"{i:>4}  {c.chunk_id:>5}  {fmt(c.rerank_score, 3):>7}   {c.text[:55]}")

print("\nTop 1 :", [c.chunk_id for c in reranker.rerank(query, candidates, top_k=1)])
print("Top 3 :", [c.chunk_id for c in reranker.rerank(query, candidates, top_k=3)])

print("\nOriginal input untouched? candidates[0].rerank_score =", candidates[0].rerank_score)
print("Original order kept?       ", [c.chunk_id for c in candidates])

print("\nEdge cases")
print("  empty query      ->", reranker.rerank("", candidates))
print("  whitespace query ->", reranker.rerank("   ", candidates))
print("  no candidates    ->", reranker.rerank(query, []))