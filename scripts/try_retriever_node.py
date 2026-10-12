from app.agents.config import AgentConfig
from app.agents.retriever_agent import make_retriever_node
from app.agents.state import initial_state
from tests.unit.agents.mocks import MockRetriever, make_chunk

config = AgentConfig()

# --- first pass: two sub-questions, one chunk ("overview") found by both
retriever = MockRetriever(
    responses={
        "deal value FY26 and FY25": [make_chunk("tcv_table"), make_chunk("overview")],
        "share of revenue": [make_chunk("revenue_split"), make_chunk("overview")],
    }
)
state = initial_state("original question")
state["subqueries"] = ["deal value FY26 and FY25", "share of revenue"]
state["search_queries"] = list(state["subqueries"])

update = make_retriever_node(retriever, config)(state)
print("--- first pass")
print("evidence:", [c.chunk_id for c in update["retrieved_chunks"]])
print("trace:", update["trace"][0].content)
print("metadata:", update["trace"][0].metadata)

# --- retry: a new search finds one new chunk; the old evidence is kept
retry_retriever = MockRetriever(
    responses={"net income Q3": [make_chunk("net_income_table"), make_chunk("overview")]}
)
state["retrieved_chunks"] = update["retrieved_chunks"]
state["search_queries"] = ["net income Q3"]
state["retry_count"] = 1

update2 = make_retriever_node(retry_retriever, config)(state)
print("--- retry")
print("evidence:", [c.chunk_id for c in update2["retrieved_chunks"]])
print("trace:", update2["trace"][0].content)
print("metadata:", update2["trace"][0].metadata)

# --- a crashing retriever does not crash the node
broken_state = initial_state("q")
broken_state["search_queries"] = ["x"]
update3 = make_retriever_node(MockRetriever(error=RuntimeError("boom")), config)(
    broken_state
)
print("--- retriever crash")
print("evidence:", update3["retrieved_chunks"])
print("trace:", update3["trace"][0].content)
print("errors:", update3["trace"][0].metadata["errors"])