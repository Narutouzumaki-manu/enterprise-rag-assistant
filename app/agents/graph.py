"""The agent graph (TRD Sections 2 and 14): wires the nodes with routing rules.

Routing decisions are plain functions of the state, so they can be tested
without a model. A set final_answer always means "done".

NOTE: routing functions name their settings parameter `agent_config`, never
`config`. LangGraph injects its own RunnableConfig into any function parameter
called `config`, which would silently replace ours.
"""
from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from app.agents.config import AgentConfig
from app.agents.fact_checker import make_fact_checker_node, make_finalize_node
from app.agents.llm import LLMClient
from app.agents.planner import make_planner_node
from app.agents.retriever_agent import Retriever, make_retriever_node
from app.agents.state import AgentState
from app.agents.synthesizer import GENERATION_FAILED_ANSWER, make_synthesizer_node
from app.schemas.agent import AgentStep, AgentStepType

# Nodes that still have to run after the retriever: synthesize + fact-check.
STEPS_AFTER_RETRIEVE = 2
# Extra room above max_steps for LangGraph's own recursion limit.
RECURSION_MARGIN = 5


def _latest_retrieve_step(state: AgentState) -> AgentStep | None:
    for step in reversed(state["trace"]):
        if step.step_type == AgentStepType.RETRIEVE:
            return step
    return None


def route_after_retrieve(state: AgentState, agent_config: AgentConfig) -> str:
    """synthesize | finalize | step_limit"""
    if state["step_count"] + STEPS_AFTER_RETRIEVE > agent_config.max_steps:
        return "step_limit"
    if state["retry_count"] > 0:
        step = _latest_retrieve_step(state)
        if step is not None and step.metadata.get("new_chunks", 0) == 0:
            # A retry found nothing new: another pass would see the same evidence.
            return "finalize"
    return "synthesize"


def route_after_synthesize(state: AgentState, agent_config: AgentConfig) -> str:
    """end | fact_check | step_limit"""
    if state["final_answer"] is not None:
        return "end"
    if state["step_count"] + 1 > agent_config.max_steps:
        return "step_limit"
    return "fact_check"


def route_after_fact_check(state: AgentState) -> str:
    """end | retry"""
    return "end" if state["final_answer"] is not None else "retry"


def make_step_limit_node() -> Callable[[AgentState], dict]:
    """Safety guard: stop and return what we have, clearly marked unverified."""

    def step_limit_node(state: AgentState) -> dict:
        draft = state["draft_answer"]
        if draft:
            content = (
                "Step limit reached before the answer was checked; "
                "returning the draft marked unverified"
            )
        else:
            content = "Step limit reached before an answer was written"
        step = AgentStep(
            step_type=AgentStepType.FACT_CHECK,
            content=content,
            metadata={
                "claims_total": 0,
                "claims_supported": 0,
                "coverage": 0.0,
                "retry": False,
                "step_limit": True,
            },
        )
        return {
            "final_answer": draft or GENERATION_FAILED_ANSWER,
            "verification_status": "unverified",
            "confidence": 0.0,
            "step_count": state["step_count"] + 1,
            "trace": [step],
        }

    return step_limit_node


def run_config(agent_config: AgentConfig) -> dict:
    """Settings for graph.invoke(): a hard stop above max_steps as a last safety net."""
    return {"recursion_limit": agent_config.max_steps + RECURSION_MARGIN}


def build_graph(retriever: Retriever, llm: LLMClient, config: AgentConfig):
    """Wire the nodes into the compiled agent graph."""

    def after_retrieve(state: AgentState) -> str:
        return route_after_retrieve(state, config)

    def after_synthesize(state: AgentState) -> str:
        return route_after_synthesize(state, config)

    graph = StateGraph(AgentState)
    graph.add_node("planner", make_planner_node(llm, config))
    graph.add_node("retriever", make_retriever_node(retriever, config))
    graph.add_node("synthesizer", make_synthesizer_node(llm))
    graph.add_node("fact_checker", make_fact_checker_node(llm, config))
    graph.add_node("finalize", make_finalize_node(config))
    graph.add_node("step_limit", make_step_limit_node())

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "retriever")
    graph.add_conditional_edges(
        "retriever",
        after_retrieve,
        {
            "synthesize": "synthesizer",
            "finalize": "finalize",
            "step_limit": "step_limit",
        },
    )
    graph.add_conditional_edges(
        "synthesizer",
        after_synthesize,
        {"fact_check": "fact_checker", "end": END, "step_limit": "step_limit"},
    )
    graph.add_conditional_edges(
        "fact_checker",
        route_after_fact_check,
        {"retry": "retriever", "end": END},
    )
    graph.add_edge("finalize", END)
    graph.add_edge("step_limit", END)
    return graph.compile()