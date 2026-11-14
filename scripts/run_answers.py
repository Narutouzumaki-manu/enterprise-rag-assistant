"""Collect answers on the frozen golden file for later hand grading.

Reuses scripts/live_agent_run.py as template (CachingLLM, same agent build, same retriever build).
"""

import argparse
import dataclasses
import hashlib
import json
import sys
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.agents.agent import build_agent
from app.agents.config import AgentConfig
from app.agents.fact_checker import Verification
from app.agents.guard import quarantine
from app.agents.llm import OpenRouterLLM
from app.agents.llm_cache import CachingLLM
from app.agents.planner import Plan
from app.agents.synthesizer import (
    GENERATION_FAILED_ANSWER,
    NO_EVIDENCE_ANSWER,
    SYSTEM_PROMPT,
    Draft,
    build_user_prompt,
    clean_text,
)
from app.eval.golden_schema import validate_golden_questions
from app.eval.validate_golden import load_chunks
from app.retrieval.factory import build_default_retriever
from app.schemas.retrieval import RetrievalRequest

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SINGLE_DRAFT_SOURCE_PATH = Path("scripts/golden_baseline_eval.py")
REFUSAL_STRING = "I don't have sufficient evidence in the provided documents."
FLAG_KEYS = {
    "fallback",
    "reason",
    "checker_failed",
    "errors",
    "stopped_early",
    "step_limit",
    "agent_error",
}


def compute_sha256(path: Path | str) -> str:
    """Calculate SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().lower()


def get_cache_namespace(variant: str) -> str:
    """Return the CachingLLM namespace for a given variant.

    full_agent and agent_no_checker share 'answers-agent-v1' so that the evaluation
    run without the fact-checker can replay the full agent's cached planner and first
    draft calls without issuing new model requests. single_draft keeps its own
    namespace 'answers-single_draft-v1' because its prompt and single-pass structure differ.
    """
    if variant in ("full_agent", "agent_no_checker"):
        return "answers-agent-v1"
    return f"answers-{variant}-v1"


def get_cache_path(variant: str, base_dir: Path | str = "data/llm_cache") -> Path:
    """Return the default LLM cache file Path for a given variant.

    The two agent variants share the planner call and the first draft, so they must
    share both namespace AND file. single_draft keeps its own file.
    """
    directory = Path(base_dir)
    # The two agent variants share the planner call and the first draft,
    # so they must share both namespace AND file.
    if variant in ("full_agent", "agent_no_checker"):
        return directory / "answers_full_agent.json"
    return directory / f"answers_{variant}.json"


get_default_cache_path = get_cache_path
get_cache_file = get_cache_path


def show_result(result: Any) -> None:
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


def show_step(step: Any) -> None:
    flags = {k: v for k, v in step.metadata.items() if k in FLAG_KEYS and v}
    extra = f"   {flags}" if flags else ""
    print(f"  step: {step.step_type.value} - {step.content}{extra}")


class TrackingLLM:
    """Wraps an LLMClient (e.g. CachingLLM), prints model answers/errors,
    and tracks per-question calls, misses, and last error."""

    def __init__(self, inner: Any, verbose: bool = True) -> None:
        self.inner = inner
        self.verbose = verbose
        self.last_error: Exception | None = None
        self.call_count_this_question: int = 0
        self.misses_this_question: int = 0
        self.total_misses: int = 0

    def reset_question(self) -> None:
        self.last_error = None
        self.call_count_this_question = 0
        self.misses_this_question = 0

    def complete(self, system: str, prompt: str) -> str:
        self.call_count_this_question += 1
        try:
            return self.inner.complete(system, prompt)
        except Exception as error:
            self.last_error = error
            if "replay-only mode" in str(error).lower() or "no cached answer" in str(error).lower():
                self.misses_this_question += 1
                self.total_misses += 1
            if self.verbose:
                print(f"   llm ERROR: {error}")
            raise

    def complete_structured(self, system: str, prompt: str, schema: type[Any]) -> Any:
        self.call_count_this_question += 1
        try:
            result = self.inner.complete_structured(system, prompt, schema)
            if self.verbose:
                show_result(result)
            return result
        except Exception as error:
            self.last_error = error
            if "replay-only mode" in str(error).lower() or "no cached answer" in str(error).lower():
                self.misses_this_question += 1
                self.total_misses += 1
            if self.verbose:
                print(f"   llm ERROR ({schema.__name__}): {error}")
            raise


def is_rate_limit_error(error: Exception | None) -> bool:
    if error is None:
        return False
    msg = str(error).lower()
    return "rate limit" in msg or "ratelimit" in msg or "429" in msg or "too many requests" in msg


def load_existing_results(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {
                item["question_id"]: item
                for item in data
                if isinstance(item, dict) and "question_id" in item
            }
        elif isinstance(data, dict):
            if "results" in data and isinstance(data["results"], list):
                return {
                    item["question_id"]: item
                    for item in data["results"]
                    if isinstance(item, dict) and "question_id" in item
                }
            return {k: v for k, v in data.items() if isinstance(v, dict)}
    except Exception:
        return {}
    return {}


def save_results(path: Path, results_by_id: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    items = list(results_by_id.values())
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def run_answers(
    expect_hash: str,
    variant: str = "full_agent",
    golden_file: Path | str = "app/eval/golden_questions.json",
    output_dir: Path | str = "app/eval/results",
    cache_path: Path | str | None = None,
    questions: list[str] | None = None,
    order: str = "unanswerable_first",
    limit: int | None = None,
    live: bool = False,
    resume: bool = False,
    retriever: Any = None,
    llm: Any = None,
    verbose: bool = True,
) -> int:
    load_dotenv()
    golden_path = Path(golden_file)
    if not golden_path.exists():
        print(f"ERROR: Golden questions file not found: {golden_path}", file=sys.stderr)
        return 1

    # 1. Required argument --expect-hash <sha256>; abort if it does not match
    current_hash = compute_sha256(golden_path)
    if expect_hash.strip().lower() != current_hash:
        print(
            f"ERROR: Hash mismatch! Expected {expect_hash.strip().lower()}, got {current_hash}",
            file=sys.stderr,
        )
        return 1

    # 2. Check variant
    if variant == "agent_no_checker":
        config_fields = {f.name for f in dataclasses.fields(AgentConfig)}
        if "use_fact_checker" not in config_fields:
            print("SKIPPED: switch not available")
            return 0
        config = AgentConfig(use_fact_checker=False)  # type: ignore[call-arg]
    elif variant == "single_draft":
        if not SINGLE_DRAFT_SOURCE_PATH.exists():
            print(
                f"ERROR: Session 20 single-draft code at {SINGLE_DRAFT_SOURCE_PATH} no longer exists.",
                file=sys.stderr,
            )
            return 1
        print(f"Reusing Session 20 single-draft code from: {SINGLE_DRAFT_SOURCE_PATH}")
        config = AgentConfig()
    elif variant == "full_agent":
        config = AgentConfig()
    else:
        print(f"ERROR: Unknown variant: {variant}", file=sys.stderr)
        return 1

    # Load and validate questions
    raw_questions = json.loads(golden_path.read_text(encoding="utf-8"))
    all_questions = validate_golden_questions(raw_questions)

    # Filter by --questions
    if questions and "all" not in [x.lower() for x in questions]:
        target_ids = set(questions)
        selected_questions = [q for q in all_questions if q.question_id in target_ids]
    else:
        selected_questions = list(all_questions)

    # Order questions: unanswerable_first is default
    if order == "unanswerable_first":
        # 0 for unanswerable, 1 for answerable (stable sort preserves original relative ordering)
        selected_questions = sorted(
            selected_questions, key=lambda q: (0 if q.category == "unanswerable" else 1)
        )

    # Output file setup
    out_dir_path = Path(output_dir)
    output_file = out_dir_path / f"answers_{variant}.json"
    existing_results = load_existing_results(output_file)

    # If resume is requested, skip questions that already succeeded without error
    if resume:
        selected_questions = [
            q
            for q in selected_questions
            if q.question_id not in existing_results
            or existing_results[q.question_id].get("error") is not None
        ]

    # Apply --limit
    if limit is not None and limit > 0:
        selected_questions = selected_questions[:limit]

    print(
        f"RUN ANSWERS: variant={variant} | questions={len(selected_questions)} "
        f"| mode={'LIVE' if live else 'REPLAY-ONLY'} | output={output_file}"
    )

    # Build retriever if not provided
    if retriever is None:
        print("Ingesting document chunks for retriever...")
        chunks = load_chunks()
        retriever = build_default_retriever(collection_name=f"answers_{uuid.uuid4().hex}")
        retriever.index_chunks(chunks)
        retriever.retrieve(RetrievalRequest(query="warm up", top_k=config.top_k))

    # Build CachingLLM if not provided
    if llm is None:
        if cache_path is None:
            cache_file = get_cache_path(variant)
        else:
            cache_file = Path(cache_path)

        # Shared namespace for full_agent and agent_no_checker so the evaluation run
        # without the fact-checker replays the full agent's planner and first draft.
        namespace = get_cache_namespace(variant)
        if not live:
            raw_cache = CachingLLM(cache_file, None, namespace=namespace, replay_only=True)
        else:
            raw_cache = CachingLLM(
                cache_file,
                lambda: OpenRouterLLM.from_env(retries=config.llm_retries),
                namespace=namespace,
                replay_only=False,
            )
        tracking_llm = TrackingLLM(raw_cache, verbose=verbose)
    else:
        raw_cache = llm
        tracking_llm = TrackingLLM(llm, verbose=verbose)

    # If full_agent or agent_no_checker, build the agent
    agent = None
    if variant in ("full_agent", "agent_no_checker"):
        agent = build_agent(retriever, tracking_llm, config)

    # Execute questions
    processed_count = 0
    cache_misses_count = 0

    for q in selected_questions:
        qid = q.question_id
        print(f"\n=== [{qid}] ({q.category}/{q.style}): {q.question}")
        tracking_llm.reset_question()
        start = time.perf_counter()

        if variant == "single_draft":
            # Session 20 single draft: search once (top_k=8), one draft, no planner, no fact-check, no retries
            resp = retriever.retrieve(RetrievalRequest(query=q.question, top_k=8))
            retrieved_chunks = list(resp.results)
            if config.quarantine_instructions:
                retrieved_chunks, _removed = quarantine(retrieved_chunks)

            answer = NO_EVIDENCE_ANSWER
            cited_ids: list[str] = []
            if retrieved_chunks:
                try:
                    user_prompt = build_user_prompt(q.question, retrieved_chunks, [], [])
                    draft = tracking_llm.complete_structured(SYSTEM_PROMPT, user_prompt, Draft)
                    cited_ids = list(draft.cited_chunk_ids)
                    if not draft.answer_found:
                        answer = NO_EVIDENCE_ANSWER
                    elif clean_text(draft.answer):
                        answer = clean_text(draft.answer)
                    else:
                        answer = GENERATION_FAILED_ANSWER
                except Exception:
                    answer = GENERATION_FAILED_ANSWER

            lat = (time.perf_counter() - start) * 1000
            chunks_by_id = {c.chunk_id: c for c in retrieved_chunks}
            citations = []
            for cid in cited_ids:
                c = chunks_by_id.get(cid)
                if c:
                    citations.append({
                        "chunk_id": c.chunk_id,
                        "page_number": getattr(c, "page_number", None),
                        "source_snippet": getattr(c, "text", "")[:200],
                    })
                else:
                    citations.append({
                        "chunk_id": cid,
                        "page_number": None,
                        "source_snippet": "",
                    })

            step_labels = ["retrieve", "synthesize"] if retrieved_chunks else ["retrieve"]
            trace = {
                "counts": dict(Counter(step_labels)),
                "labels": step_labels,
            }
            verification_status = "unverified"
            confidence = 0.0

        else:
            # full_agent / agent_no_checker
            response = agent.run(q.question)
            lat = (time.perf_counter() - start) * 1000
            answer = response.answer
            verification_status = response.verification_status
            confidence = response.confidence
            citations = [
                {
                    "chunk_id": c.chunk_id,
                    "page_number": c.page_number,
                    "source_snippet": c.text_snippet,
                }
                for c in response.citations
            ]
            step_labels = [
                s.step_type.value if hasattr(s.step_type, "value") else str(s.step_type)
                for s in response.trace
            ]
            trace = {
                "counts": dict(Counter(step_labels)),
                "labels": step_labels,
            }

        refused = bool(answer == REFUSAL_STRING)
        error_text = str(tracking_llm.last_error) if tracking_llm.last_error is not None else None

        record = {
            "question_id": qid,
            "category": q.category,
            "style": q.style,
            "answer": answer,
            "verification_status": verification_status,
            "confidence": confidence,
            "citations": citations,
            "trace": trace,
            "llm_calls": tracking_llm.call_count_this_question,
            "latency_ms": round(lat, 1),
            "refused": refused,
            "error": error_text,
            "golden_hash": current_hash,
        }

        # Merge by question_id and persist immediately
        existing_results[qid] = record
        save_results(output_file, existing_results)
        processed_count += 1

        if tracking_llm.misses_this_question > 0:
            cache_misses_count += 1
            print(f"  [{qid}] REPLAY CACHE MISS: {tracking_llm.last_error}")
        else:
            print(f"  [{qid}] ANSWER: {answer[:90]!r} (status={verification_status}, calls={tracking_llm.call_count_this_question})")

        if live:
            total_requests = getattr(raw_cache, "misses", 0)
            print(f"  [{qid}] Live model requests made so far in this run: {total_requests}")
            if is_rate_limit_error(tracking_llm.last_error):
                print(f"\nRate-limit error detected on {qid}: {tracking_llm.last_error}")
                print(f"Stopping cleanly with partial results ({len(existing_results)} questions) saved.")
                break

    live_total = getattr(raw_cache, "misses", 0)
    print("\n" + "=" * 70)
    print(f"COMPLETED RUN: processed={processed_count} | cache_misses={cache_misses_count} | live_requests={live_total}")
    print(f"Results saved to: {output_file}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect answers on frozen golden questions.")
    parser.add_argument(
        "--expect-hash",
        type=str,
        required=True,
        help="Expected SHA-256 hash of golden questions file",
    )
    parser.add_argument(
        "--variant",
        choices=["single_draft", "full_agent", "agent_no_checker"],
        default="full_agent",
        help="Evaluation variant",
    )
    parser.add_argument(
        "--golden-file",
        type=str,
        default="app/eval/golden_questions.json",
        help="Path to golden questions JSON",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="app/eval/results",
        help="Directory to save answer results JSON",
    )
    parser.add_argument(
        "--cache-path",
        type=str,
        default=None,
        help="Optional path to LLM cache JSON",
    )
    parser.add_argument(
        "--questions",
        nargs="+",
        default=["all"],
        help="Question IDs to run or 'all'",
    )
    parser.add_argument(
        "--order",
        choices=["unanswerable_first", "original"],
        default="unanswerable_first",
        help="Question evaluation ordering",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of questions to evaluate in this run",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Enable live model calls (otherwise runs in replay-only mode)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip questions already present without error in results",
    )

    args = parser.parse_args(argv)
    return run_answers(
        expect_hash=args.expect_hash,
        variant=args.variant,
        golden_file=args.golden_file,
        output_dir=args.output_dir,
        cache_path=args.cache_path,
        questions=args.questions,
        order=args.order,
        limit=args.limit,
        live=args.live,
        resume=args.resume,
    )


if __name__ == "__main__":
    sys.exit(main())
