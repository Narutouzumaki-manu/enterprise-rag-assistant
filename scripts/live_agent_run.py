"""First live run of the whole agent on the real TCS index.

  python -m scripts.live_agent_run                live: about 3 to 7 LLM calls per question
  python -m scripts.live_agent_run --only q19     one question
  python -m scripts.live_agent_run --replay       free: replays saved answers, never calls the model

Every model answer is saved to data/llm_cache/live_run.json (git-ignored), so
running the same thing again costs nothing.
"""
import argparse
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from app.agents.agent import build_agent
from app.agents.config import AgentConfig
from app.agents.fact_checker import Verification
from app.agents.llm import DEFAULT_MODEL, LLMError, OpenRouterLLM
from app.agents.llm_cache import CachingLLM
from app.agents.planner import Plan
from app.agents.synthesizer import Draft
from app.retrieval.factory import build_default_retriever
from app.schemas.agent import AgentResponse
from app.schemas.retrieval import RetrievalRequest
from scripts.run_comparison import load_labels_and_chunks

sys.stdout.reconfigure(encoding="utf-8")

CACHE_PATH = Path("data/llm_cache/live_run.json")
RESULTS_PATH = Path("data/eval/live_agent_run.json")
KEYS_PATH = Path("data/eval/retrieval_questions.json")
WORST_CASE_CALLS = 7  # planner + (draft + check) x 3 passes
FLAG_KEYS = {"fallback", "reason", "checker_failed", "errors", "stopped_early",
             "step_limit", "agent_error"}

QUESTIONS = {
    "simple": "What was the closing headcount at the end of Q2 FY26?",
    "q16": (
        "How did the value of new deals from the biggest market change over the "
        "year, and roughly what portion of revenue does that market make up?"
    ),
    "q19": (
        "What was the company's profit after tax in the October-to-December "
        "quarter of the year before FY26?"
    ),
}
REFERENCE_NOTES = {
    "simple": "probably 593,314 (the example in Member 2's handoff; confirm in the report)",
}


def reference_answers() -> dict:
    """Member 2's reference answers, if the question file has them."""
    if not KEYS_PATH.exists():
        return {}
    try:
        data = json.loads(KEYS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    items = data["questions"] if isinstance(data, dict) and "questions" in data else data
    if not isinstance(items, list):
        return {}
    return {
        q.get("question_id"): q.get("reference_answer")
        for q in items
        if isinstance(q, dict) and q.get("reference_answer")
    }


def show_result(result) -> None:
    if isinstance(result, Plan):
        print(f"   llm plan: {result.query_type}; sub-queries: {result.subqueries}")
    elif isinstance(result, Draft):
        extra = "" if result.answer_found else f"  NOT FOUND, search: {result.search_query!r}"
        print(f"   llm draft: {result.answer!r}  cited: {result.cited_chunk_ids}{extra}")
    elif isinstance(result, Verification):
        for verdict in result.verdicts:
            mark = "supported" if verdict.supported else "NOT supported"
            hint = f"  hint: {verdict.search_query!r}" if verdict.search_query else ""
            print(f"   llm claim: {verdict.claim!r} -> {mark} {verdict.supporting_chunk_ids}{hint}")


class ShowingLLM:
    """Prints every model answer (live or replayed) and every error, then passes it on."""

    def __init__(self, inner) -> None:
        self.inner = inner

    def complete(self, system, prompt):
        try:
            return self.inner.complete(system, prompt)
        except LLMError as error:
            print(f"   llm ERROR: {error}")
            raise

    def complete_structured(self, system, prompt, schema):
        try:
            result = self.inner.complete_structured(system, prompt, schema)
        except LLMError as error:
            print(f"   llm ERROR ({schema.__name__}): {error}")
            raise
        show_result(result)
        return result


def show_step(step) -> None:
    flags = {k: v for k, v in step.metadata.items() if k in FLAG_KEYS and v}
    extra = f"   {flags}" if flags else ""
    print(f"  step: {step.step_type.value} - {step.content}{extra}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="+", choices=list(QUESTIONS))
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--max-requests", type=int, default=21)
    args = parser.parse_args()

    load_dotenv()
    names = args.only or list(QUESTIONS)
    config = AgentConfig()

    _, chunks = load_labels_and_chunks()
    retriever = build_default_retriever(collection_name=f"live_{uuid.uuid4().hex}")
    retriever.index_chunks(chunks)
    retriever.retrieve(RetrievalRequest(query="warm up", top_k=config.top_k))

    model = os.getenv("OPENROUTER_MODEL") or DEFAULT_MODEL
    if args.replay:
        cache = CachingLLM(CACHE_PATH, None, namespace=model, replay_only=True)
    else:
        cache = CachingLLM(
            CACHE_PATH,
            lambda: OpenRouterLLM.from_env(retries=config.llm_retries),
            namespace=model,
        )
    agent = build_agent(retriever, ShowingLLM(cache), config)
    references = reference_answers()

    print(f"LIVE RUN: {'REPLAY (no model calls)' if args.replay else 'LIVE'} | model {model}")
    print(f"questions: {names} | cache: {CACHE_PATH}")

    results = []
    for name in names:
        if not args.replay and cache.misses + WORST_CASE_CALLS > args.max_requests:
            print(f"\nStopping before {name}: {cache.misses} calls made, "
                  f"the next question could use {WORST_CASE_CALLS} more, "
                  f"limit is {args.max_requests} (raise --max-requests to continue).")
            break

        question = QUESTIONS[name]
        reference = references.get(name) or REFERENCE_NOTES.get(name)
        before_misses, before_hits = cache.misses, cache.hits
        print(f"\n=== {name}: {question}")
        if reference:
            print(f"    reference answer: {reference}")

        final = None
        for event in agent.run_streaming(question):
            if isinstance(event, AgentResponse):
                final = event
            else:
                show_step(event)

        used, replayed = cache.misses - before_misses, cache.hits - before_hits
        print(f"  ANSWER: {final.answer}")
        print(f"  status: {final.verification_status} | confidence: {final.confidence}")
        for citation in final.citations:
            print(f"   [{citation.chunk_id} p.{citation.page_number}] {citation.text_snippet[:90]}")
        print(f"  model calls: {used} live, {replayed} replayed | "
              f"time: {final.latency_ms / 1000:.1f} s | trace steps: {len(final.trace)}")

        results.append({
            "name": name,
            "question": question,
            "reference_answer": reference,
            "model_calls_live": used,
            "model_calls_replayed": replayed,
            "response": final.model_dump(mode="json"),
        })

    print(f"\nTOTAL: {cache.misses} live model calls, {cache.hits} replayed")
    print("Run again with --replay to see everything again for free.")

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(
        json.dumps(
            {
                "run_at": datetime.now(UTC).isoformat(),
                "model": model,
                "replay": args.replay,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("saved to", RESULTS_PATH)


if __name__ == "__main__":
    main()