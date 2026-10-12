from langgraph.graph import END, START, StateGraph

from app.agents.state import AgentState, initial_state
from app.schemas.agent import AgentStep, AgentStepType


def node_a(state: AgentState) -> dict:
    return {
        "step_count": state["step_count"] + 1,
        "trace": [AgentStep(step_type=AgentStepType.PLAN, content="a ran")],
    }


def node_b(state: AgentState) -> dict:
    return {
        "step_count": state["step_count"] + 1,
        "trace": [AgentStep(step_type=AgentStepType.RETRIEVE, content="b ran")],
    }


# Check 1: two requests must not share lists
s1 = initial_state("question one")
s2 = initial_state("question two")
s1["subqueries"].append("x")
print("check 1 - s2 subqueries still empty:", s2["subqueries"] == [])

# Check 2: the trace accumulates through a real LangGraph run
graph = StateGraph(AgentState)
graph.add_node("a", node_a)
graph.add_node("b", node_b)
graph.add_edge(START, "a")
graph.add_edge("a", "b")
graph.add_edge("b", END)
app = graph.compile()

final = app.invoke(initial_state("test question"))
print("check 2 - step_count (expect 2):", final["step_count"])
print("check 2 - trace (expect a ran, then b ran):", [s.content for s in final["trace"]])
print("check 3 - query untouched:", final["query"])
print("check 3 - still unverified:", final["verification_status"])