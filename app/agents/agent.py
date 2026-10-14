"""Public entry point of the agent (UI/UX doc Section 2).

build_agent() is called ONCE per process; run() and run_streaming() are called
per question. Whatever happens inside, the caller always gets a valid
AgentResponse: this module never raises to its caller.
"""
import logging
import time
from collections.abc import Callable, Iterator

from app.agents.config import TOP_K_LIMIT, AgentConfig
from app.agents.graph import build_graph, run_config
from app.agents.llm import LLMClient
from app.agents.retriever_agent import Retriever
from app.agents.state import AgentState, initial_state
from app.agents.synthesizer import GENERATION_FAILED_ANSWER
from app.schemas.agent import AgentResponse, AgentStep, AgentStepType

logger = logging.getLogger(__name__)

EMPTY_QUERY_ANSWER = "Please enter a question."
VALID_STATUSES = {"verified", "partially_verified", "unverified"}


def _build_response(
    state: AgentState, started: float, clock: Callable[[], float]
) -> AgentResponse:
    """Turn the final state into the response, sanitising what the caller sees."""
    answer = state["final_answer"]
    status = state["verification_status"]
    confidence = state["confidence"]

    if answer is None:
        # No node finished the run: return what we have, clearly unverified.
        answer = state["draft_answer"] or GENERATION_FAILED_ANSWER
        status = "unverified"
    if status not in VALID_STATUSES:
        status = "unverified"
    if status == "unverified":
        confidence = 0.0

    return AgentResponse(
        answer=answer,
        citations=list(state["citations"]),
        trace=list(state["trace"]),
        verification_status=status,
        confidence=min(max(float(confidence), 0.0), 1.0),
        latency_ms=(clock() - started) * 1000,
    )


def _stopped_state(state: AgentState, error: Exception) -> tuple[AgentState, AgentStep]:
    """State to report when the graph failed. Only the error's type name goes
    into the trace; details stay in the log."""
    step = AgentStep(
        step_type=AgentStepType.FACT_CHECK,
        content="The agent stopped unexpectedly; returning what is available marked unverified",
        metadata={"agent_error": type(error).__name__},
    )
    stopped = dict(state)
    stopped["trace"] = list(state["trace"]) + [step]
    stopped["final_answer"] = (
        state["final_answer"] or state["draft_answer"] or GENERATION_FAILED_ANSWER
    )
    stopped["verification_status"] = "unverified"
    stopped["confidence"] = 0.0
    return stopped, step  # type: ignore[return-value]


class Agent:
    """Holds the compiled graph. Keeps no per-question state, so one Agent can
    serve many questions."""

    def __init__(
        self,
        graph,
        config: AgentConfig,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.graph = graph
        self.config = config
        self.clock = clock

    def run_streaming(
        self,
        query: str,
        session_context: dict | None = None,  # reserved for chat history; unused for now
        top_k: int | None = None,
    ) -> Iterator[AgentStep | AgentResponse]:
        """Yield each trace step as it happens, then the final AgentResponse."""
        started = self.clock()

        if not isinstance(query, str) or not query.strip():
            yield AgentResponse(
                answer=EMPTY_QUERY_ANSWER,
                citations=[],
                trace=[],
                verification_status="unverified",
                confidence=0.0,
                latency_ms=(self.clock() - started) * 1000,
            )
            return

        chosen_top_k = (
            self.config.top_k
            if top_k is None
            else min(max(int(top_k), 1), TOP_K_LIMIT)
        )
        state = initial_state(query, top_k=chosen_top_k)
        last = state
        seen = 0
        try:
            for current in self.graph.stream(
                state, run_config(self.config), stream_mode="values"
            ):
                last = current
                for step in current["trace"][seen:]:
                    yield step
                seen = len(current["trace"])
        except Exception as error:
            logger.exception("Agent run failed")
            stopped, step = _stopped_state(last, error)
            yield step
            yield _build_response(stopped, started, self.clock)
            return

        yield _build_response(last, started, self.clock)

    def run(
        self,
        query: str,
        session_context: dict | None = None,
        top_k: int | None = None,
    ) -> AgentResponse:
        """Answer one question and return the final AgentResponse."""
        response: AgentResponse | None = None
        for event in self.run_streaming(query, session_context, top_k):
            if isinstance(event, AgentResponse):
                response = event
        # run_streaming always ends with an AgentResponse
        return response  # type: ignore[return-value]


def build_agent(
    retriever: Retriever, llm: LLMClient, config: AgentConfig | None = None
) -> Agent:
    """Build the agent once per process."""
    config = config or AgentConfig()
    return Agent(build_graph(retriever, llm, config), config)