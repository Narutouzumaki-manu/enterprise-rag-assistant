from app.agents.llm import LLMError
from app.agents.state import initial_state
from app.agents.synthesizer import Draft, make_synthesizer_node
from tests.unit.agents.mocks import MockLLM, make_chunk


def show(title, chunks, scripted):
    state = initial_state("What was revenue?")
    state["retrieved_chunks"] = chunks
    llm = MockLLM(structured={Draft: [scripted]})
    update = make_synthesizer_node(llm)(state)
    print(f"--- {title}")
    print("generator calls:", len(llm.calls))
    print("draft:", repr(update["draft_answer"]))
    print("final:", update.get("final_answer"))
    print("status:", update.get("verification_status", "(not set)"))
    print("citations:", [(c.chunk_id, c.page_number) for c in update["citations"]])
    print("trace:", update["trace"][0].content)
    print("metadata:", update["trace"][0].metadata)


evidence = [
    make_chunk("rev_table", text="Revenue: 2,500 crore", page_number=12),
    make_chunk("overview"),
]

show(
    "normal: one real citation, one made-up",
    evidence,
    Draft(answer="Revenue was 2,500 crore.", cited_chunk_ids=["rev_table", "ghost"]),
)
show("no evidence", [], Draft(answer="unused"))
show("LLM failure", evidence, LLMError("down"))