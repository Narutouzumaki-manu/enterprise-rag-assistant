import logging

from langgraph.errors import GraphRecursionError

from app.agents.agent import EMPTY_QUERY_ANSWER, Agent, build_agent
from app.agents.config import AgentConfig
from app.agents.fact_checker import ClaimVerdict, Verification
from app.agents.planner import Plan
from app.agents.state import initial_state
from app.agents.synthesizer import GENERATION_FAILED_ANSWER, NO_EVIDENCE_ANSWER, Draft
from app.schemas.agent import AgentResponse, AgentStep, AgentStepType
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


def clean_llm(copies=1):
    return MockLLM(
        structured={
            Plan: [PLAN] * copies,
            Draft: [Draft(answer="Revenue was 5.", cited_chunk_ids=["a"])] * copies,
            Verification: [
                Verification(verdicts=[verdict("Revenue was 5", True, ["a"])])
            ]
            * copies,
        }
    )


def retry_scenario():
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
    return llm, retriever


def partly_unsupported_llm():
    return MockLLM(
        structured={
            Plan: [PLAN],
            Draft: [Draft(answer="Revenue was 5. Net income was 2.", cited_chunk_ids=["a"])],
            Verification: [
                Verification(
                    verdicts=[
                        verdict("Revenue was 5", True, ["a"]),
                        verdict("Net income was 2", False, query="q1"),
                    ]
                )
            ],
        }
    )


class FakeGraph:
    """Stands in for the compiled graph: replays states, then optionally fails."""

    def __init__(self, states, error=None):
        self.states = states
        self.error = error
        self.finished = False
        self.calls = []

    def stream(self, state, config=None, stream_mode=None):
        self.calls.append((config, stream_mode))
        for current in self.states:
            yield current
        self.finished = True
        if self.error is not None:
            raise self.error


def make_clock(*values):
    iterator = iter(values)
    return lambda: next(iterator)


def types(response):
    return [step.step_type for step in response.trace]


STEP_ONE = AgentStep(step_type=AgentStepType.PLAN, content="p")
STEP_TWO = AgentStep(step_type=AgentStepType.RETRIEVE, content="r")


# ---- run() through the real graph -------------------------------------

def test_clean_question_gives_a_valid_response():
    response = build_agent(MockRetriever(responses={Q: [REV]}), clean_llm()).run(Q)
    assert isinstance(response, AgentResponse)
    assert response.answer == "Revenue was 5."
    assert response.verification_status == "verified"
    assert response.confidence == 0.95
    assert [c.chunk_id for c in response.citations] == ["a"]
    assert types(response) == [
        AgentStepType.PLAN,
        AgentStepType.RETRIEVE,
        AgentStepType.SYNTHESIZE,
        AgentStepType.FACT_CHECK,
    ]
    assert response.latency_ms >= 0


def test_no_evidence_gives_the_insufficient_evidence_answer():
    response = build_agent(MockRetriever(), MockLLM(structured={Plan: [PLAN]})).run(Q)
    assert response.answer == NO_EVIDENCE_ANSWER
    assert response.verification_status == "unverified"
    assert response.confidence == 0.0
    assert response.citations == []


def test_retry_returns_the_final_verified_answer():
    llm, retriever = retry_scenario()
    response = build_agent(retriever, llm).run(Q)
    assert response.answer == "Revenue was 5. Net income was 2."
    assert response.verification_status == "verified"
    assert len(response.trace) == 7


def test_partially_verified_response():
    retriever = MockRetriever(responses={Q: [REV]})
    response = build_agent(retriever, partly_unsupported_llm()).run(Q)
    assert response.verification_status == "partially_verified"
    assert response.confidence == 0.5
    assert "- Net income was 2" in response.answer


def test_latency_is_measured_in_milliseconds():
    final = initial_state(Q)
    final.update(final_answer="Done", verification_status="verified", confidence=0.9)
    agent = Agent(FakeGraph([final]), AgentConfig(), clock=make_clock(10.0, 10.25))
    assert agent.run(Q).latency_ms == 250.0


# ---- the request's inputs ---------------------------------------------

def test_top_k_from_the_request_reaches_the_retriever():
    retriever = MockRetriever(responses={Q: [REV]})
    build_agent(retriever, clean_llm()).run(Q, top_k=12)
    assert retriever.calls[0].top_k == 12


def test_top_k_is_clamped_to_the_backend_limit():
    retriever = MockRetriever(responses={Q: [REV]})
    agent = build_agent(retriever, clean_llm(copies=2))
    agent.run(Q, top_k=99)
    agent.run(Q, top_k=0)
    assert retriever.calls[0].top_k == 20
    assert retriever.calls[1].top_k == 1


def test_default_top_k_comes_from_config():
    retriever = MockRetriever(responses={Q: [REV]})
    config = AgentConfig(top_k=5)
    build_agent(retriever, clean_llm(), config).run(Q)
    assert retriever.calls[0].top_k == 5


def test_blank_question_is_answered_without_any_calls():
    llm, retriever = clean_llm(), MockRetriever(responses={Q: [REV]})
    agent = build_agent(retriever, llm)
    for blank in ("", "   "):
        response = agent.run(blank)
        assert response.answer == EMPTY_QUERY_ANSWER
        assert response.verification_status == "unverified"
        assert response.confidence == 0.0
        assert response.trace == []
    assert llm.calls == []
    assert retriever.calls == []


def test_session_context_is_accepted():
    agent = build_agent(MockRetriever(responses={Q: [REV]}), clean_llm())
    response = agent.run(Q, session_context={"session_id": "s1"})
    assert response.verification_status == "verified"


# ---- streaming --------------------------------------------------------

def test_streaming_yields_steps_in_order_then_the_response():
    agent = build_agent(MockRetriever(responses={Q: [REV]}), clean_llm())
    events = list(agent.run_streaming(Q))
    *steps, final = events
    assert all(isinstance(step, AgentStep) for step in steps)
    assert [step.step_type for step in steps] == [
        AgentStepType.PLAN,
        AgentStepType.RETRIEVE,
        AgentStepType.SYNTHESIZE,
        AgentStepType.FACT_CHECK,
    ]
    assert isinstance(final, AgentResponse)


def test_streaming_yields_steps_as_they_happen():
    base = initial_state(Q)
    first_state = {**base, "trace": [STEP_ONE]}
    last_state = {
        **base,
        "trace": [STEP_ONE, STEP_TWO],
        "final_answer": "x",
        "verification_status": "unverified",
    }
    graph = FakeGraph([first_state, last_state])
    generator = Agent(graph, AgentConfig()).run_streaming(Q)

    first = next(generator)
    assert first == STEP_ONE
    assert graph.finished is False

    rest = list(generator)
    assert graph.finished is True
    assert rest[0] == STEP_TWO
    assert isinstance(rest[1], AgentResponse)
    assert len(rest) == 2


def test_streamed_steps_match_the_response_trace():
    llm, retriever = retry_scenario()
    events = list(build_agent(retriever, llm).run_streaming(Q))
    *steps, final = events
    assert steps == final.trace


# ---- failures ---------------------------------------------------------

def test_recursion_limit_error_becomes_a_valid_response():
    state = {**initial_state(Q), "draft_answer": "Draft", "trace": [STEP_ONE]}
    graph = FakeGraph([state], error=GraphRecursionError("limit"))
    response = Agent(graph, AgentConfig()).run(Q)
    assert response.answer == "Draft"
    assert response.verification_status == "unverified"
    assert response.confidence == 0.0
    assert len(response.trace) == 2
    assert response.trace[-1].step_type == AgentStepType.FACT_CHECK
    assert response.trace[-1].metadata == {"agent_error": "GraphRecursionError"}


def test_unexpected_error_before_any_progress():
    graph = FakeGraph([], error=RuntimeError("boom"))
    response = Agent(graph, AgentConfig()).run(Q)
    assert response.answer == GENERATION_FAILED_ANSWER
    assert response.verification_status == "unverified"
    assert len(response.trace) == 1
    assert response.trace[0].metadata == {"agent_error": "RuntimeError"}


def test_error_step_is_streamed_before_the_final_response():
    graph = FakeGraph([], error=RuntimeError("boom"))
    events = list(Agent(graph, AgentConfig()).run_streaming(Q))
    assert isinstance(events[-1], AgentResponse)
    assert isinstance(events[-2], AgentStep)
    assert events[-2].metadata["agent_error"] == "RuntimeError"
    assert events[-1].trace[-1] == events[-2]


def test_error_details_are_not_leaked():
    graph = FakeGraph([], error=RuntimeError("secret detail"))
    response = Agent(graph, AgentConfig()).run(Q)
    assert "secret detail" not in response.model_dump_json()


def test_error_is_logged(caplog):
    graph = FakeGraph([], error=RuntimeError("boom"))
    with caplog.at_level(logging.ERROR, logger="app.agents.agent"):
        Agent(graph, AgentConfig()).run(Q)
    assert "Agent run failed" in caplog.text


def test_graph_without_a_final_answer_returns_the_draft_unverified():
    with_draft = {**initial_state(Q), "draft_answer": "Draft"}
    response = Agent(FakeGraph([with_draft]), AgentConfig()).run(Q)
    assert response.answer == "Draft"
    assert response.verification_status == "unverified"
    assert response.confidence == 0.0

    response = Agent(FakeGraph([initial_state(Q)]), AgentConfig()).run(Q)
    assert response.answer == GENERATION_FAILED_ANSWER
    assert response.verification_status == "unverified"


def test_status_and_confidence_are_sanitised():
    def run_with(**overrides):
        state = {**initial_state(Q), "final_answer": "x", **overrides}
        return Agent(FakeGraph([state]), AgentConfig()).run(Q)

    invalid = run_with(verification_status="weird", confidence=0.9)
    assert invalid.verification_status == "unverified"
    assert invalid.confidence == 0.0

    assert run_with(verification_status="verified", confidence=7.0).confidence == 1.0
    assert run_with(verification_status="verified", confidence=-1.0).confidence == 0.0


# ---- reuse and wiring -------------------------------------------------

def test_two_runs_do_not_share_state():
    retriever = MockRetriever(responses={Q: [REV]})
    agent = build_agent(retriever, clean_llm(copies=2))
    first = agent.run(Q)
    second = agent.run(Q)
    assert len(first.trace) == 4
    assert len(second.trace) == 4
    assert first.verification_status == second.verification_status == "verified"
    assert len(retriever.calls) == 2


def test_build_agent_uses_the_given_config():
    config = AgentConfig(max_retries=0, max_steps=4)
    retriever = MockRetriever(responses={Q: [REV]})
    agent = build_agent(retriever, partly_unsupported_llm(), config)
    response = agent.run(Q)
    assert agent.config is config
    assert response.verification_status == "partially_verified"
    assert len(response.trace) == 4
    assert len(retriever.calls) == 1


def test_response_is_json_serialisable():
    response = build_agent(MockRetriever(responses={Q: [REV]}), clean_llm()).run(Q)
    assert AgentResponse.model_validate_json(response.model_dump_json()) == response


def test_graph_receives_the_recursion_limit_and_values_mode():
    final = {**initial_state(Q), "final_answer": "x", "verification_status": "unverified"}
    graph = FakeGraph([final])
    Agent(graph, AgentConfig()).run(Q)
    assert graph.calls == [({"recursion_limit": 17}, "values")]


def test_evaluation_mode_without_fact_checker():
    config = AgentConfig(use_fact_checker=False)
    retriever = MockRetriever(responses={Q: [REV]})
    llm = clean_llm()
    agent = build_agent(retriever, llm, config)
    response = agent.run(Q)

    assert isinstance(response, AgentResponse)
    assert response.answer == "Revenue was 5."
    assert response.verification_status == "unverified"
    assert response.confidence == 0.0
    assert [c.chunk_id for c in response.citations] == ["a"]
    assert llm.structured_calls(Verification) == []

    skip_step = response.trace[-1]
    assert skip_step.step_type == AgentStepType.FACT_CHECK
    assert skip_step.content == "Fact-check skipped (evaluation mode)"
    assert skip_step.metadata == {"fact_check_skipped": True}