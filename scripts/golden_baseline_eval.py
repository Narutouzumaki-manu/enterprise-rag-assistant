"""Baseline on the golden questions (Session 20): search once, write ONE draft.
No planner, no fact-check, no retries. Uses the same prompt, cache and namespace
as the full agent, so a simple question replays the agent's first draft for free.

  python -m scripts.golden_baseline_eval --only tcs-gold-02
  python -m scripts.golden_baseline_eval
  python -m scripts.golden_baseline_eval --replay
"""
import argparse
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from app.agents.config import AgentConfig
from app.agents.guard import quarantine
from app.agents.llm import DEFAULT_MODEL, LLMError, OpenRouterLLM
from app.agents.llm_cache import CachingLLM
from app.agents.synthesizer import (
    GENERATION_FAILED_ANSWER,
    NO_EVIDENCE_ANSWER,
    SYSTEM_PROMPT,
    Draft,
    build_user_prompt,
    clean_text,
)
from app.ingestion.pipeline import ingest_document
from app.retrieval.factory import build_default_retriever
from app.schemas.retrieval import RetrievalRequest
from scripts.golden_agent_eval import (
    CACHE_PATH,
    LABELS_PATH,
    NAMESPACE,
    PDF_PATH,
    QUESTIONS_PATH,
)
from scripts.live_agent_run import ShowingLLM

sys.stdout.reconfigure(encoding="utf-8")

RESULTS_PATH = Path("data/eval/golden_baseline_results.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="+")
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--max-requests", type=int, default=12)
    args = parser.parse_args()

    load_dotenv()
    config = AgentConfig()
    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    if args.only:
        questions = [q for q in questions if q["question_id"] in args.only]

    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    result = ingest_document(PDF_PATH)
    if len(result.chunks) != labels["chunk_count"]:
        print(f"STOP: {len(result.chunks)} chunks now, labels were made on {labels['chunk_count']}")
        return 1

    retriever = build_default_retriever(collection_name=f"s20b_{uuid.uuid4().hex}")
    retriever.index_chunks(result.chunks)
    retriever.retrieve(RetrievalRequest(query="warm up", top_k=config.top_k))

    model = os.getenv("OPENROUTER_MODEL") or DEFAULT_MODEL
    if args.replay:
        cache = CachingLLM(CACHE_PATH, None, namespace=NAMESPACE, replay_only=True)
    else:
        cache = CachingLLM(
            CACHE_PATH,
            lambda: OpenRouterLLM.from_env(retries=config.llm_retries),
            namespace=NAMESPACE,
        )
    llm = ShowingLLM(cache)

    print(f"GOLDEN BASELINE: {'REPLAY' if args.replay else 'LIVE'} | model {model} | namespace {NAMESPACE}")
    results = []
    for q in questions:
        if not args.replay and cache.misses + 1 > args.max_requests:
            print(f"\nStopping before {q['question_id']}: {cache.misses} live calls, limit {args.max_requests}.")
            break

        print(f"\n=== {q['question_id']} [{q['category']}]: {q['question']}")
        print(f"    reference: {q.get('reference_answer') or '(none: unanswerable)'}")
        before_misses, before_hits = cache.misses, cache.hits

        response = retriever.retrieve(RetrievalRequest(query=q["question"], top_k=config.top_k))
        chunks = list(response.results)
        if config.quarantine_instructions:
            chunks, _removed = quarantine(chunks)

        answer, answer_found, cited, status = NO_EVIDENCE_ANSWER, False, [], "no_evidence"
        if chunks:
            try:
                draft = llm.complete_structured(
                    SYSTEM_PROMPT, build_user_prompt(q["question"], chunks, [], []), Draft
                )
                cited = list(draft.cited_chunk_ids)
                if not draft.answer_found:
                    status = "not_found"
                elif clean_text(draft.answer):
                    answer, answer_found, status = clean_text(draft.answer), True, "answered"
                else:
                    answer, status = GENERATION_FAILED_ANSWER, "llm_failed"
            except LLMError:
                answer, status = GENERATION_FAILED_ANSWER, "llm_failed"

        used, replayed = cache.misses - before_misses, cache.hits - before_hits
        print(f"  BASELINE ANSWER: {answer}")
        print(f"  status: {status} | model calls: {used} live, {replayed} replayed")

        results.append({
            "question_id": q["question_id"],
            "category": q["category"],
            "question": q["question"],
            "reference_answer": q.get("reference_answer", ""),
            "baseline_status": status,
            "answer": answer,
            "answer_found": answer_found,
            "cited_chunk_ids": cited,
            "model_calls_live": used,
            "model_calls_replayed": replayed,
            "passages": [
                {"chunk_id": c.chunk_id, "page_number": c.page_number, "text": c.text}
                for c in chunks
            ],
        })

    print(f"\nTOTAL: {cache.misses} live model calls, {cache.hits} replayed")
    RESULTS_PATH.write_text(json.dumps({
        "run_at": datetime.now(UTC).isoformat(),
        "model": model,
        "namespace": NAMESPACE,
        "replay": args.replay,
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved to", RESULTS_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())