from app.schemas.retrieval import RetrievalRequest
from tests.unit.agents.mocks import MockRetriever, make_chunk

a = make_chunk("a", dense_score=0.9)
b = make_chunk("b", dense_score=0.8)
c = make_chunk("c", dense_score=0.7)
retriever = MockRetriever(responses={"revenue": [a, b, c]})

r1 = retriever.retrieve(RetrievalRequest(query="revenue", top_k=2))
print("check 1 - top_k=2 gives a, b:", [x.chunk_id for x in r1.results])

r2 = retriever.retrieve(RetrievalRequest(query="something else"))
print("check 2 - unknown query is empty:", r2.results == [])

r3 = retriever.retrieve(RetrievalRequest(query=""))
print("check 3 - empty query is empty:", r3.results == [])

print("check 4 - calls recorded:", [call.query for call in retriever.calls])
print("check 5 - sparse score is None:", r1.results[0].sparse_score is None)

r1.results[0].text = "EDITED"
r4 = retriever.retrieve(RetrievalRequest(query="revenue"))
print("check 6 - mock not affected by edits:", r4.results[0].text)

try:
    retriever.retrieve(RetrievalRequest(query="revenue", filters={"colour": "red"}))
    print("check 7 - FAILED: bad filter accepted")
except ValueError as error:
    print("check 7 - bad filter rejected:", error)

broken = MockRetriever(error=RuntimeError("boom"))
try:
    broken.retrieve(RetrievalRequest(query="x"))
    print("check 8 - FAILED: no error raised")
except RuntimeError as error:
    print("check 8 - error raised:", error)