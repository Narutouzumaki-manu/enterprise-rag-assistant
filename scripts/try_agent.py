from langgraph.errors import GraphRecursionError

from app.agents.agent import Agent, build_agent
from app.agents.config import AgentConfig
from app.agents.fact_checker import ClaimVerdict, Verification
from app.agents.planner import Plan
from app.schemas.agent import AgentResponse
from tests.unit.agents.mocks import MockLLM, MockRetriever, make_chunk

Q = "What was revenue?"
PLAN = Plan(query_type="simple", subqueries=[Q])
REV = make_chunk("a", text="Revenue was 5.")
NET = make_chunk("b", text="Net income was 2.")


def verdict(claim, supported, ids=(), query=""):
    return ClaimVerdict(
        claim=claim,
        supported=supported,
        supporting_chunk_ids=list(ids),
        search_query=query,
    )


def show(response, last_step=False):
    print("answer:", repr(response.answer))
    print("status:", response.verification_status, "| confidence:", response.confidence)
    print("citations:", [c.chunk_id for c in response.citations])
    print("trace steps:", len(response.trace), "| latency under 1s:", response.latency_ms < 1000)
    if last_step:
        print("last step:", response.trace[-1].content)


print("--- A: run() on a clean question")
from app.agents.synthesizer import Draft

llm = MockLLM(
    structured={
        Plan: [PLAN],
        Draft: [Draft(answer="Revenue was 5.", cited_chunk_ids=["a"])],
        Verification: [Verification(verdicts=[verdict("Revenue was 5", True, ["a"])])],
    }
)
show(build_agent(MockRetriever(responses={Q: [REV]}), llm).run(Q))

print("--- B: run_streaming() on a question that needs a retry")
llm = MockLLM(
    structured={
        Plan: [PLAN],
        Draft: [
            Draft(answer="Revenue was 5. Net income was 9.", cited_chunk_ids=["a"]),
            Draft(answer="Revenue was 5. Net income was 2.", cited_chunk_ids=["a", "b"]),
        ],
        Verification: [
            Verification(
                verdicts=[
                    verdict("Revenue was 5", True, ["a"]),
                    verdict("Net income was 9", False, query="net income table"),
                ]
            ),
            Verification(
                verdicts=[
                    verdict("Revenue was 5", True, ["a"]),
                    verdict("Net income was 2", True, ["b"]),
                ]
            ),
        ],
    }
)
retriever = MockRetriever(responses={Q: [REV], "net income table": [NET]})
for event in build_agent(retriever, llm).run_streaming(Q):
    if isinstance(event, AgentResponse):
        print(
            "  RESPONSE:", repr(event.answer), "|",
            event.verification_status, "|", event.confidence,
        )
    else:
        print(f"  step: {event.step_type.value} - {event.content}")

print("--- C: blank question")
show(build_agent(MockRetriever(), MockLLM()).run("   "))

print("--- D: the graph fails halfway")


class BrokenGraph:
    def stream(self, state, config=None, stream_mode=None):
        yield {**state, "draft_answer": "A half-finished draft."}
        raise GraphRecursionError("simulated: step limit")


show(Agent(BrokenGraph(), AgentConfig()).run(Q), last_step=True)