from app.agents.config import AgentConfig
from app.agents.fact_checker import ClaimVerdict, Verification
from app.agents.graph import build_graph, run_config
from app.agents.planner import Plan
from app.agents.state import initial_state
from app.agents.synthesizer import Draft
from tests.unit.agents.mocks import MockLLM, MockRetriever, make_chunk

Q = "What was revenue?"
PLAN = Plan(query_type="simple", subqueries=[Q])


def verdict(claim, supported, ids=(), query=""):
    return ClaimVerdict(
        claim=claim,
        supported=supported,
        supporting_chunk_ids=list(ids),
        search_query=query,
    )


def show(title, drafts, checks, responses):
    config = AgentConfig()
    llm = MockLLM(structured={Plan: [PLAN], Draft: drafts, Verification: checks})
    graph = build_graph(MockRetriever(responses=responses), llm, config)
    final = graph.invoke(initial_state(Q), run_config(config))
    print(f"--- {title}")
    print("final:", repr(final["final_answer"]))
    print("status:", final["verification_status"], "| confidence:", final["confidence"])
    print("steps:", final["step_count"], "| retries:", final["retry_count"])
    for step in final["trace"]:
        print("  ", step.step_type.value, "-", step.content)


REV = make_chunk("a", text="Revenue was 5.")
NET = make_chunk("b", text="Net income was 2.")

show(
    "1: clean question",
    [Draft(answer="Revenue was 5.", cited_chunk_ids=["a"])],
    [Verification(verdicts=[verdict("Revenue was 5", True, ["a"])])],
    {Q: [REV]},
)
show(
    "2: wrong draft, retry finds the missing table",
    [
        Draft(answer="Revenue was 5. Net income was 9.", cited_chunk_ids=["a"]),
        Draft(answer="Revenue was 5. Net income was 2.", cited_chunk_ids=["a", "b"]),
    ],
    [
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
    {Q: [REV], "net income table": [NET]},
)
show("3: nothing found", [], [], {})
show(
    "4: retry finds nothing new, so it stops early",
    [Draft(answer="Revenue was 5. Net income was 2.", cited_chunk_ids=["a"])],
    [
        Verification(
            verdicts=[
                verdict("Revenue was 5", True, ["a"]),
                verdict("Net income was 2", False, query="q1"),
            ]
        )
    ],
    {Q: [REV]},
)