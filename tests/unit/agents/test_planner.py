from langgraph.graph import END, START, StateGraph

from app.agents.config import AgentConfig
from app.agents.llm import LLMError
from app.agents.planner import Plan, make_planner_node
from app.agents.state import AgentState, initial_state
from app.schemas.agent import AgentStepType
from tests.unit.agents.mocks import MockLLM

Q = "What was revenue?"
Q19 = (
    "What was the company's profit after tax in the October-to-December "
    "quarter of the year before FY26?"
)

REWRITES_ON = AgentConfig(use_rewrites=True)

def run(scripted, query=Q, config=None):
    llm = MockLLM(structured={Plan: [scripted]})
    node = make_planner_node(llm, config or AgentConfig())
    return node(initial_state(query)), llm


def test_simple_query_uses_the_original_as_its_only_search():
    update, _ = run(Plan(query_type="simple", subqueries=["something else"]))
    assert update["query_type"] == "simple"
    assert update["subqueries"] == [Q]
    assert update["search_queries"] == [Q]


def test_decomposed_query_gets_one_subquery_per_fact():
    facts = ["deal value FY26 and FY25", "share of revenue"]
    update, _ = run(Plan(query_type="multi-hop", subqueries=facts))
    assert update["subqueries"] == facts
    # the original question is always searched first, then the sub-questions
    assert update["search_queries"] == [Q] + facts


def test_rewrite_adds_a_second_search_after_the_original():
    plan = Plan(
        query_type="simple",
        subqueries=[Q19],
        rewrites={Q19: "Net income Q3 FY25"},
    )
    update, _ = run(plan, query=Q19, config=REWRITES_ON)
    assert update["search_queries"] == [Q19, "Net income Q3 FY25"]


def test_rewrite_matching_ignores_case_and_extra_spaces():
    plan = Plan(
        query_type="simple",
        subqueries=[Q],
        rewrites={"  what WAS   revenue? ": "Total revenue"},
    )
    update, _ = run(plan, config=REWRITES_ON)
    assert update["search_queries"] == [Q, "Total revenue"]


def test_rewrite_identical_to_the_original_is_ignored():
    plan = Plan(
        query_type="simple",
        subqueries=[Q],
        rewrites={Q: "what was  REVENUE?"},
    )
    update, _ = run(plan, config=REWRITES_ON)
    assert update["search_queries"] == [Q]


def test_rewrite_for_an_unknown_subquery_is_ignored():
    plan = Plan(
        query_type="simple",
        subqueries=[Q],
        rewrites={"another question entirely": "something"},
    )
    update, _ = run(plan, config=REWRITES_ON)
    assert update["search_queries"] == [Q]


def test_blank_rewrite_is_ignored():
    plan = Plan(query_type="simple", subqueries=[Q], rewrites={Q: "   "})
    update, _ = run(plan, config=REWRITES_ON)
    assert update["search_queries"] == [Q]


def test_each_subquery_gets_its_own_rewrite_in_order():
    plan = Plan(
        query_type="multi-hop",
        subqueries=["a fact", "b fact"],
        rewrites={"a fact": "A term", "b fact": "B term"},
    )
    update, _ = run(plan, config=REWRITES_ON)
    assert update["search_queries"] == [Q, "a fact", "A term", "b fact", "B term"]


def test_more_than_max_subqueries_is_truncated():
    facts = [f"fact {i}" for i in range(7)]
    update, _ = run(Plan(query_type="multi-hop", subqueries=facts))
    assert update["subqueries"] == facts[:5]
    assert update["search_queries"] == [Q] + facts[:5]


def test_duplicate_and_blank_subqueries_are_removed():
    plan = Plan(
        query_type="multi-hop",
        subqueries=["fact one", "  ", "Fact  One", "fact two"],
    )
    update, _ = run(plan)
    assert update["subqueries"] == ["fact one", "fact two"]


def test_no_usable_subqueries_falls_back_to_the_original():
    plan = Plan(query_type="multi-hop", subqueries=["", "  "])
    update, _ = run(plan)
    assert update["subqueries"] == [Q]
    assert update["search_queries"] == [Q]


def test_simple_type_ignores_extra_subqueries():
    update, _ = run(Plan(query_type="simple", subqueries=["a", "b"]))
    assert update["subqueries"] == [Q]


def test_ambiguous_type_is_not_decomposed():
    update, _ = run(Plan(query_type="ambiguous", subqueries=["x", "y"]))
    assert update["query_type"] == "ambiguous"
    assert update["subqueries"] == [Q]


def test_llm_failure_falls_back_to_the_original_question():
    update, _ = run(LLMError("down"))
    assert update["query_type"] == "simple"
    assert update["subqueries"] == [Q]
    assert update["search_queries"] == [Q]


def test_fallback_is_flagged_in_the_trace():
    update, _ = run(LLMError("down"))
    step = update["trace"][0]
    assert step.step_type == AgentStepType.PLAN
    assert step.metadata["fallback"] is True
    assert "original" in step.content


def test_invalid_query_type_falls_back():
    update, _ = run({"query_type": "weird", "subqueries": ["q"]})
    assert update["query_type"] == "simple"
    assert update["trace"][0].metadata["fallback"] is True


def test_step_count_goes_up_by_one():
    node = make_planner_node(
        MockLLM(structured={Plan: [Plan(query_type="simple", subqueries=[Q])] * 2}),
        AgentConfig(),
    )
    assert node(initial_state(Q))["step_count"] == 1
    state = initial_state(Q)
    state["step_count"] = 3
    assert node(state)["step_count"] == 4


def test_trace_has_one_plan_step_with_metadata():
    update, _ = run(Plan(query_type="simple", subqueries=[Q]))
    assert len(update["trace"]) == 1
    step = update["trace"][0]
    assert step.step_type == AgentStepType.PLAN
    assert step.metadata == {
        "query_type": "simple",
        "subquery_count": 1,
        "rewritten": False,
    }


def test_trace_wording():
    plan = Plan(
        query_type="multi-hop",
        subqueries=["a fact", "b fact"],
        rewrites={"a fact": "A term"},
    )
    update, _ = run(plan, config=REWRITES_ON)
    assert update["trace"][0].content == (
        "Classified as multi-hop; 2 sub-queries; "
        "1 reworded to match the document's terms"
    )
    update, _ = run(Plan(query_type="simple", subqueries=[Q]))
    assert update["trace"][0].content == "Classified as simple; 1 sub-query"


def test_only_planner_fields_are_updated():
    update, _ = run(Plan(query_type="simple", subqueries=[Q]))
    assert set(update.keys()) == {
        "query_type",
        "subqueries",
        "search_queries",
        "step_count",
        "trace",
    }


def test_prompt_contains_question_and_subquery_limit():
    _, llm = run(
        Plan(query_type="simple", subqueries=[Q]),
        config=AgentConfig(max_subqueries=3),
    )
    call = llm.calls[0]
    assert "at most 3 sub-questions" in call.system
    assert Q in call.prompt


def test_planner_makes_exactly_one_llm_call():
    _, llm = run(Plan(query_type="simple", subqueries=[Q]))
    assert len(llm.calls) == 1
    assert len(llm.structured_calls(Plan)) == 1
    assert llm.complete_calls == []


def test_planner_node_runs_inside_a_langgraph_graph():
    llm = MockLLM(structured={Plan: [Plan(query_type="simple", subqueries=[Q])]})
    graph = StateGraph(AgentState)
    graph.add_node("planner", make_planner_node(llm, AgentConfig()))
    graph.add_edge(START, "planner")
    graph.add_edge("planner", END)

    final = graph.compile().invoke(initial_state(Q))
    assert final["query_type"] == "simple"
    assert final["search_queries"] == [Q]
    assert final["step_count"] == 1
    assert [s.step_type for s in final["trace"]] == [AgentStepType.PLAN]


def test_rewrites_are_not_searched_by_default():
    plan = Plan(
        query_type="simple",
        subqueries=[Q19],
        rewrites={Q19: "Net income Q3 FY25"},
    )
    update, _ = run(plan, query=Q19)
    assert update["search_queries"] == [Q19]
    assert update["trace"][0].metadata["rewritten"] is False
    assert update["trace"][0].content == "Classified as simple; 1 sub-query"