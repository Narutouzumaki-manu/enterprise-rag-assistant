from langgraph.graph import END, START, StateGraph

from app.agents.state import AgentState, initial_state
from app.schemas.agent import AgentStep, AgentStepType


def test_initial_state_sets_query_and_default_top_k():
    state = initial_state("what was revenue?")
    assert state["query"] == "what was revenue?"
    assert state["top_k"] == 8


def test_initial_state_accepts_custom_top_k():
    assert initial_state("q", top_k=15)["top_k"] == 15


def test_initial_state_fails_safe():
    state = initial_state("q")
    assert state["verification_status"] == "unverified"
    assert state["confidence"] == 0.0
    assert state["final_answer"] is None
    assert state["retry_count"] == 0
    assert state["step_count"] == 0


def test_initial_state_has_every_field():
    state = initial_state("q")
    assert set(state.keys()) == set(AgentState.__annotations__.keys())


def test_two_states_do_not_share_lists():
    s1 = initial_state("one")
    s2 = initial_state("two")
    s1["subqueries"].append("x")
    s1["trace"].append(AgentStep(step_type=AgentStepType.PLAN, content="p"))
    assert s2["subqueries"] == []
    assert s2["trace"] == []


def test_trace_appends_across_nodes_in_a_graph():
    def node_a(state: AgentState) -> dict:
        return {"trace": [AgentStep(step_type=AgentStepType.PLAN, content="a")]}

    def node_b(state: AgentState) -> dict:
        return {"trace": [AgentStep(step_type=AgentStepType.RETRIEVE, content="b")]}

    graph = StateGraph(AgentState)
    graph.add_node("a", node_a)
    graph.add_node("b", node_b)
    graph.add_edge(START, "a")
    graph.add_edge("a", "b")
    graph.add_edge("b", END)

    final = graph.compile().invoke(initial_state("q"))
    assert [s.content for s in final["trace"]] == ["a", "b"]
def test_initial_state_starts_with_no_citations():
    assert initial_state("q")["citations"] == []


def test_two_states_do_not_share_the_citations_list():
    s1 = initial_state("one")
    s2 = initial_state("two")
    s1["citations"].append("x")
    assert s2["citations"] == []

def test_initial_state_starts_with_no_tried_queries():
    assert initial_state("q")["tried_queries"] == []


def test_two_states_do_not_share_the_tried_queries_list():
    s1 = initial_state("one")
    s2 = initial_state("two")
    s1["tried_queries"].append("x")
    assert s2["tried_queries"] == []