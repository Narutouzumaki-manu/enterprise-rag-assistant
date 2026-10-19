from app.agents.config import AgentConfig
from app.agents.fact_checker import ClaimVerdict, Verification
from app.agents.graph import (
    build_graph,
    make_step_limit_node,
    route_after_fact_check,
    route_after_retrieve,
    route_after_synthesize,
    run_config,
)
from app.agents.llm import LLMError
from app.agents.planner import Plan
from app.agents.state import initial_state
from app.agents.synthesizer import (
    GENERATION_FAILED_ANSWER,
    NO_EVIDENCE_ANSWER,
    Draft,
)
from app.schemas.agent import AgentStep, AgentStepType
from tests.unit.agents.mocks import MockLLM, MockRetriever, make_chunk

Q = "What was revenue?"
CONFIG = AgentConfig()


def state_with(**overrides):
    state = initial_state(Q)
    state.update(overrides)
    return state


def retrieve_step(new_chunks):
    return AgentStep(
        step_type=AgentStepType.RETRIEVE,
        content="r",
        metadata={"new_chunks": new_chunks},
    )


def verdict(claim, supported, ids=(), query=""):
    return ClaimVerdict(
        claim=claim,
        supported=supported,
        supporting_chunk_ids=list(ids),
        search_query=query,
    )


def scripted_llm(plan=None, drafts=(), checks=()):
    return MockLLM(
        structured={
            Plan: [plan or Plan(query_type="simple", subqueries=[Q])],
            Draft: list(drafts),
            Verification: list(checks),
        }
    )


def run(llm, retriever, config=None):
    config = config or AgentConfig()
    graph = build_graph(retriever, llm, config)
    return graph.invoke(initial_state(Q), run_config(config))


def types(final):
    return [step.step_type for step in final["trace"]]


REV = make_chunk("a", text="Revenue was 5.")


# ---- routing after the retriever --------------------------------------

def test_first_pass_goes_from_retrieve_to_synthesize():
    state = state_with(step_count=2, retrieved_chunks=[make_chunk("a")])
    assert route_after_retrieve(state, CONFIG) == "synthesize"
    # empty evidence also goes to the synthesizer, which writes the no-evidence answer
    assert route_after_retrieve(state_with(step_count=2), CONFIG) == "synthesize"


def test_retry_with_new_passages_goes_to_synthesize():
    state = state_with(step_count=5, retry_count=1, trace=[retrieve_step(2)])
    assert route_after_retrieve(state, CONFIG) == "synthesize"


def test_retry_with_no_new_passages_goes_to_finalize():
    state = state_with(step_count=5, retry_count=1, trace=[retrieve_step(0)])
    assert route_after_retrieve(state, CONFIG) == "finalize"


def test_only_the_latest_retrieve_step_decides():
    older_empty = state_with(
        step_count=8, retry_count=2, trace=[retrieve_step(0), retrieve_step(2)]
    )
    assert route_after_retrieve(older_empty, CONFIG) == "synthesize"
    latest_empty = state_with(
        step_count=8, retry_count=2, trace=[retrieve_step(3), retrieve_step(0)]
    )
    assert route_after_retrieve(latest_empty, CONFIG) == "finalize"


def test_retrieve_with_no_room_left_goes_to_step_limit():
    # synthesize + fact-check still need 2 steps; max_steps is 12
    assert route_after_retrieve(state_with(step_count=11), CONFIG) == "step_limit"
    assert route_after_retrieve(state_with(step_count=10), CONFIG) == "synthesize"


# ---- routing after the synthesizer and the fact-checker ---------------

def test_synthesizer_with_final_answer_goes_to_end():
    state = state_with(step_count=3, final_answer="done")
    assert route_after_synthesize(state, CONFIG) == "end"


def test_synthesizer_draft_goes_to_fact_check():
    assert route_after_synthesize(state_with(step_count=3), CONFIG) == "fact_check"


def test_synthesizer_with_no_room_left_goes_to_step_limit():
    assert route_after_synthesize(state_with(step_count=12), CONFIG) == "step_limit"


def test_fact_checker_routes_to_end_or_retry():
    assert route_after_fact_check(state_with(final_answer="done")) == "end"
    assert route_after_fact_check(state_with(final_answer=None)) == "retry"


# ---- the step-limit node ----------------------------------------------

def test_step_limit_node_returns_the_draft_marked_unverified():
    update = make_step_limit_node()(state_with(draft_answer="Draft", step_count=12))
    assert update["final_answer"] == "Draft"
    assert update["verification_status"] == "unverified"
    assert update["confidence"] == 0.0
    step = update["trace"][0]
    assert step.step_type == AgentStepType.FACT_CHECK
    assert step.content == (
        "Step limit reached before the answer was checked; "
        "returning the draft marked unverified"
    )
    assert step.metadata == {
        "claims_total": 0,
        "claims_supported": 0,
        "coverage": 0.0,
        "retry": False,
        "step_limit": True,
    }


def test_step_limit_node_without_a_draft_says_it_could_not_write_one():
    update = make_step_limit_node()(state_with(step_count=12))
    assert update["final_answer"] == GENERATION_FAILED_ANSWER
    assert update["trace"][0].content == "Step limit reached before an answer was written"


def test_step_limit_node_touches_only_expected_fields():
    update = make_step_limit_node()(state_with(draft_answer="Draft", step_count=12))
    assert set(update.keys()) == {
        "final_answer",
        "verification_status",
        "confidence",
        "step_count",
        "trace",
    }
    assert update["step_count"] == 13


def test_run_config_sets_a_recursion_limit_above_max_steps():
    assert run_config(AgentConfig()) == {"recursion_limit": 17}
    assert run_config(AgentConfig(max_retries=3, max_steps=13)) == {"recursion_limit": 18}


# ---- the whole graph on mocks -----------------------------------------

def test_clean_question_runs_the_four_nodes_and_is_verified():
    llm = scripted_llm(
        drafts=[Draft(answer="Revenue was 5.", cited_chunk_ids=["a"])],
        checks=[Verification(verdicts=[verdict("Revenue was 5", True, ["a"])])],
    )
    final = run(llm, MockRetriever(responses={Q: [REV]}))
    assert final["verification_status"] == "verified"
    assert final["final_answer"] == "Revenue was 5."
    assert final["step_count"] == 4
    assert final["retry_count"] == 0
    assert types(final) == [
        AgentStepType.PLAN,
        AgentStepType.RETRIEVE,
        AgentStepType.SYNTHESIZE,
        AgentStepType.FACT_CHECK,
    ]
    assert len(llm.calls) == 3


def test_no_evidence_ends_after_the_synthesizer_without_a_fact_check():
    llm = scripted_llm()
    final = run(llm, MockRetriever())
    assert final["final_answer"] == NO_EVIDENCE_ANSWER
    assert final["verification_status"] == "unverified"
    assert final["step_count"] == 3
    assert llm.structured_calls(Draft) == []
    assert llm.structured_calls(Verification) == []
    assert types(final) == [
        AgentStepType.PLAN,
        AgentStepType.RETRIEVE,
        AgentStepType.SYNTHESIZE,
    ]


def test_generator_failure_ends_without_a_fact_check():
    llm = scripted_llm(drafts=[LLMError("down")])
    final = run(llm, MockRetriever(responses={Q: [REV]}))
    assert final["final_answer"] == GENERATION_FAILED_ANSWER
    assert final["verification_status"] == "unverified"
    assert final["step_count"] == 3
    assert llm.structured_calls(Verification) == []


def test_fact_checker_failure_returns_the_draft_unverified():
    llm = scripted_llm(
        drafts=[Draft(answer="Revenue was 5.", cited_chunk_ids=["a"])],
        checks=[LLMError("down")],
    )
    final = run(llm, MockRetriever(responses={Q: [REV]}))
    assert final["final_answer"] == "Revenue was 5."
    assert final["verification_status"] == "unverified"
    assert final["confidence"] == 0.0
    assert final["step_count"] == 4
    assert final["trace"][-1].metadata["checker_failed"] is True


def test_retry_loop_recovers_missing_evidence():
    llm = scripted_llm(
        drafts=[
            Draft(answer="Revenue was 5. Net income was 9.", cited_chunk_ids=["a"]),
            Draft(answer="Revenue was 5. Net income was 2.", cited_chunk_ids=["a", "b"]),
        ],
        checks=[
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
    )
    retriever = MockRetriever(
        responses={
            Q: [REV],
            "net income table": [make_chunk("b", text="Net income was 2.")],
        }
    )
    final = run(llm, retriever)
    assert final["verification_status"] == "verified"
    assert final["final_answer"] == "Revenue was 5. Net income was 2."
    assert final["step_count"] == 7
    assert final["retry_count"] == 1
    assert [c.query for c in retriever.calls] == [Q, "Net income was 9", "net income table"]
    assert [c.chunk_id for c in final["retrieved_chunks"]] == ["b", "a"]
    assert len(llm.structured_calls(Draft)) == 2
    assert len(llm.structured_calls(Verification)) == 2
    assert types(final) == [
        AgentStepType.PLAN,
        AgentStepType.RETRIEVE,
        AgentStepType.SYNTHESIZE,
        AgentStepType.FACT_CHECK,
        AgentStepType.RETRIEVE,
        AgentStepType.SYNTHESIZE,
        AgentStepType.FACT_CHECK,
    ]


def test_two_retries_finish_within_the_step_cap():
    draft = Draft(answer="Revenue was 5.", cited_chunk_ids=["a"])
    checks = [
        Verification(verdicts=[verdict("Revenue was 5", False, query=hint)])
        for hint in ("q1", "q2", "q3")
    ]
    llm = scripted_llm(drafts=[draft] * 3, checks=checks)
    retriever = MockRetriever(
        responses={Q: [REV], "q1": [make_chunk("b")], "q2": [make_chunk("c")]}
    )
    final = run(llm, retriever)
    assert final["step_count"] == 10
    assert final["step_count"] <= AgentConfig().max_steps
    assert final["retry_count"] == 2
    assert final["top_k"] == 15
    assert retriever.calls[0].top_k == 8
    assert retriever.calls[-1].top_k == 15
    assert [c.chunk_id for c in final["retrieved_chunks"]] == ["c", "b", "a"]
    assert final["final_answer"] == NO_EVIDENCE_ANSWER
    assert final["verification_status"] == "unverified"
    assert len(final["trace"]) == 10


def test_retry_without_new_passages_stops_early():
    llm = scripted_llm(
        drafts=[Draft(answer="Revenue was 5. Net income was 2.", cited_chunk_ids=["a"])],
        checks=[
            Verification(
                verdicts=[
                    verdict("Revenue was 5", True, ["a"]),
                    verdict("Net income was 2", False, query="q1"),
                ]
            )
        ],
    )
    final = run(llm, MockRetriever(responses={Q: [REV]}))
    assert final["verification_status"] == "partially_verified"
    assert final["confidence"] == 0.5
    assert "- Net income was 2" in final["final_answer"]
    assert final["step_count"] == 6
    assert final["retry_count"] == 1
    assert len(llm.structured_calls(Draft)) == 1
    assert len(llm.structured_calls(Verification)) == 1
    assert final["trace"][-2].content == "No new passages found"
    assert final["trace"][-1].metadata["stopped_early"] is True


def test_minimal_config_runs_exactly_the_first_pass():
    config = AgentConfig(max_retries=0, max_steps=4)

    llm = scripted_llm(
        drafts=[Draft(answer="Revenue was 5.", cited_chunk_ids=["a"])],
        checks=[Verification(verdicts=[verdict("Revenue was 5", True, ["a"])])],
    )
    final = run(llm, MockRetriever(responses={Q: [REV]}), config)
    assert final["verification_status"] == "verified"
    assert final["step_count"] == 4

    # a partly unsupported answer is finished without any retry
    llm = scripted_llm(
        drafts=[Draft(answer="Revenue was 5. Net income was 2.", cited_chunk_ids=["a"])],
        checks=[
            Verification(
                verdicts=[
                    verdict("Revenue was 5", True, ["a"]),
                    verdict("Net income was 2", False, query="q1"),
                ]
            )
        ],
    )
    retriever = MockRetriever(responses={Q: [REV]})
    final = run(llm, retriever, config)
    assert final["verification_status"] == "partially_verified"
    assert final["step_count"] == 4
    assert final["retry_count"] == 0
    assert len(retriever.calls) == 1


def test_planner_failure_still_gets_an_answer():
    llm = scripted_llm(
        plan=LLMError("down"),
        drafts=[Draft(answer="Revenue was 5.", cited_chunk_ids=["a"])],
        checks=[Verification(verdicts=[verdict("Revenue was 5", True, ["a"])])],
    )
    retriever = MockRetriever(responses={Q: [REV]})
    final = run(llm, retriever)
    assert final["trace"][0].metadata["fallback"] is True
    assert retriever.calls[0].query == Q
    assert final["verification_status"] == "verified"
    assert final["step_count"] == 4

# ---- the passages do not contain the answer ---------------------------

def synth_step(**metadata):
    return AgentStep(
        step_type=AgentStepType.SYNTHESIZE, content="s", metadata=metadata
    )


def test_synthesizer_not_found_goes_back_to_the_retriever():
    state = state_with(step_count=3, trace=[synth_step(retry_search=True)])
    assert route_after_synthesize(state, CONFIG) == "retry_search"
    normal = state_with(step_count=3, trace=[synth_step(citation_count=1)])
    assert route_after_synthesize(normal, CONFIG) == "fact_check"


def test_not_found_draft_triggers_a_new_search_and_recovers():
    table = make_chunk("table", text="Net income Q3 FY25: 12,380 crore")
    llm = scripted_llm(
        drafts=[
            Draft(
                answer="The passages do not say.",
                answer_found=False,
                search_query="net income Q3 FY25",
            ),
            Draft(answer="Profit after tax was 12,380 crore.", cited_chunk_ids=["table"]),
        ],
        checks=[
            Verification(
                verdicts=[verdict("Profit after tax was 12,380 crore", True, ["table"])]
            )
        ],
    )
    retriever = MockRetriever(responses={Q: [REV], "net income Q3 FY25": [table]})
    final = run(llm, retriever)
    assert final["verification_status"] == "verified"
    assert final["final_answer"] == "Profit after tax was 12,380 crore."
    assert [c.query for c in retriever.calls] == [Q, "net income Q3 FY25"]
    assert final["step_count"] == 6
    assert final["retry_count"] == 1
    assert types(final) == [
        AgentStepType.PLAN,
        AgentStepType.RETRIEVE,
        AgentStepType.SYNTHESIZE,
        AgentStepType.RETRIEVE,
        AgentStepType.SYNTHESIZE,
        AgentStepType.FACT_CHECK,
    ]
    assert len(llm.structured_calls(Draft)) == 2
    assert len(llm.structured_calls(Verification)) == 1


def test_not_found_twice_ends_with_insufficient_evidence_and_no_fact_check():
    def missing(hint):
        return Draft(answer="Not in the passages.", answer_found=False, search_query=hint)

    llm = scripted_llm(drafts=[missing("h1"), missing("h2"), missing("h3")])
    retriever = MockRetriever(
        responses={Q: [REV], "h1": [make_chunk("b")], "h2": [make_chunk("c")]}
    )
    final = run(llm, retriever)
    assert final["final_answer"] == NO_EVIDENCE_ANSWER
    assert final["verification_status"] == "unverified"
    assert final["step_count"] == 7
    assert final["retry_count"] == 2
    assert final["top_k"] == 15
    assert retriever.calls[-1].top_k == 15
    assert llm.structured_calls(Verification) == []


def test_not_found_and_no_new_passages_stops_early():
    llm = scripted_llm(
        drafts=[
            Draft(answer="Not in the passages.", answer_found=False, search_query="h1")
        ]
    )
    retriever = MockRetriever(responses={Q: [REV]})  # "h1" finds nothing
    final = run(llm, retriever)
    assert final["final_answer"] == NO_EVIDENCE_ANSWER
    assert final["step_count"] == 5
    assert len(llm.structured_calls(Draft)) == 1
    assert final["trace"][-1].metadata["stopped_early"] is True

def test_a_repeated_search_hint_triggers_a_wider_search_of_the_question():
    def missing(hint):
        return Draft(answer="Not in the passages.", answer_found=False, search_query=hint)

    llm = scripted_llm(drafts=[missing("h1"), missing("h1"), missing("h3")])
    retriever = MockRetriever(
        responses={
            Q: [make_chunk(f"c{i}") for i in range(12)],
            "h1": [make_chunk("x")],
        }
    )
    final = run(llm, retriever)
    assert [c.query for c in retriever.calls] == [Q, "h1", Q]
    assert [c.top_k for c in retriever.calls] == [8, 8, 15]
    assert final["final_answer"] == NO_EVIDENCE_ANSWER
    assert final["step_count"] == 7
    assert final["tried_queries"] == [Q, "h1"]