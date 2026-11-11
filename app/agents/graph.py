"""The agent graph (TRD Sections 2 and 14): wires the nodes with routing rules.

Routing decisions are plain functions of the state, so they can be tested
without a model. A set final_answer always means "done".

synthesizer ── retry_search → retriever  (the passages did not contain the answer)

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


def _latest_step(state: AgentState, step_type: AgentStepType) -> AgentStep | None:
    for step in reversed(state["trace"]):
        if step.step_type == step_type:
            return step
    return None


def route_after_retrieve(state: AgentState, agent_config: AgentConfig) -> str:
    """synthesize | finalize | step_limit"""
    if state["step_count"] + STEPS_AFTER_RETRIEVE > agent_config.max_steps:
        return "step_limit"
    if state["retry_count"] > 0:
        step = _latest_step(state, AgentStepType.RETRIEVE)
        if step is not None and step.metadata.get("new_chunks", 0) == 0:
            # A retry found nothing new: another pass would see the same evidence.
            return "finalize"
    return "synthesize"


def route_after_synthesize(state: AgentState, agent_config: AgentConfig) -> str:
    """end | retry_search | fact_check | skip_fact_check | step_limit"""
    if state["final_answer"] is not None:
        return "end"
    step = _latest_step(state, AgentStepType.SYNTHESIZE)
    if step is not None and step.metadata.get("retry_search"):
        # the passages did not contain the answer: search again, skip the fact-check
        return "retry_search"
    if state["step_count"] + 1 > agent_config.max_steps:
        return "step_limit"
    if not agent_config.use_fact_checker:
        return "skip_fact_check"
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


def make_skip_fact_check_node() -> Callable[[AgentState], dict]:
    """Evaluation switch: skip fact-checking and return the draft as final."""

    def skip_fact_check_node(state: AgentState) -> dict:
        step = AgentStep(
            step_type=AgentStepType.FACT_CHECK,
            content="Fact-check skipped (evaluation mode)",
            metadata={"fact_check_skipped": True},
        )
        return {
            "final_answer": state["draft_answer"],
            "citations": list(state["citations"]),
            "verification_status": "unverified",
            "confidence": 0.0,
            "step_count": state["step_count"] + 1,
            "trace": [step],
        }

    return skip_fact_check_node


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
    graph.add_node("synthesizer", make_synthesizer_node(llm, config))    
    graph.add_node("fact_checker", make_fact_checker_node(llm, config))
    graph.add_node("finalize", make_finalize_node(config))
    graph.add_node("step_limit", make_step_limit_node())
    graph.add_node("skip_fact_check", make_skip_fact_check_node())

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
        {
            "fact_check": "fact_checker",
            "skip_fact_check": "skip_fact_check",
            "retry_search": "retriever",
            "end": END,
            "step_limit": "step_limit",
        },
    )
    graph.add_conditional_edges(
        "fact_checker",
        route_after_fact_check,
        {"retry": "retriever", "end": END},
    )
    graph.add_edge("finalize", END)
    graph.add_edge("step_limit", END)
    graph.add_edge("skip_fact_check", END)
    return graph.compile()