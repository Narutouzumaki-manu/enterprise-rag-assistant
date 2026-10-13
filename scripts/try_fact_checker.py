from app.agents.config import AgentConfig
from app.agents.fact_checker import ClaimVerdict, Verification, make_fact_checker_node
from app.agents.llm import LLMError
from app.agents.state import initial_state
from tests.unit.agents.mocks import MockLLM, make_chunk

EVIDENCE = [
    make_chunk("rev_table", text="Revenue: 2,500 crore", page_number=12),
    make_chunk("overview"),
]
TWO_SENTENCES = "Revenue was 2,500 crore. Net income was 700 crore."
REV_OK = ClaimVerdict(
    claim="Revenue was 2,500 crore", supported=True, supporting_chunk_ids=["rev_table"]
)
NET_BAD = ClaimVerdict(
    claim="Net income was 700 crore", supported=False, search_query="net income FY26"
)


def show(title, scripted, draft=TWO_SENTENCES, **overrides):
    state = initial_state("What were revenue and net income?")
    state["retrieved_chunks"] = EVIDENCE
    state["draft_answer"] = draft
    state.update(overrides)
    llm = MockLLM(structured={Verification: [scripted]})
    update = make_fact_checker_node(llm, AgentConfig())(state)
    print(f"--- {title}")
    print("final:", repr(update.get("final_answer")))
    print("status:", update.get("verification_status", "(not set)"))
    print(
        "coverage:", update["coverage"],
        "| confidence:", update.get("confidence", "(not set)"),
    )
    print(
        "citations:",
        [c.chunk_id for c in update["citations"]] if "citations" in update else "(unchanged)",
    )
    print(
        "retry_count:", update.get("retry_count", "(unchanged)"),
        "| search_queries:", update.get("search_queries", "(unchanged)"),
    )
    print("trace:", update["trace"][0].content)


show("A: verified", Verification(verdicts=[REV_OK]), draft="Revenue was 2,500 crore.")
show("B: one claim unsupported, retry needed", Verification(verdicts=[REV_OK, NET_BAD]))
show("C: retries used up", Verification(verdicts=[REV_OK, NET_BAD]), retry_count=2)
show(
    "D: nothing supported, retries used up",
    Verification(verdicts=[NET_BAD]),
    retry_count=2,
)
show("E: the checker call fails", LLMError("down"))