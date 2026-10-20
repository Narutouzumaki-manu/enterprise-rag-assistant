"""Full-agent run on the golden questions (Session 20).

  python -m scripts.golden_agent_eval --only tcs-gold-02   pilot: one question, about 3 live calls
  python -m scripts.golden_agent_eval                      all questions, stops at the budget
  python -m scripts.golden_agent_eval --replay             free: replays saved answers only
"""
import argparse
import dataclasses
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from app.agents.agent import build_agent
from app.agents.config import AgentConfig
from app.agents.llm import DEFAULT_MODEL, OpenRouterLLM
from app.agents.llm_cache import CachingLLM
from app.ingestion.pipeline import ingest_document
from app.retrieval.factory import build_default_retriever
from app.schemas.agent import AgentResponse
from app.schemas.retrieval import RetrievalRequest
from scripts.live_agent_run import ShowingLLM, show_step

sys.stdout.reconfigure(encoding="utf-8")

PDF_PATH = "data/eval/documents/tcs_annual_report.pdf"
QUESTIONS_PATH = Path("data/eval/golden_questions_resolved.json")
LABELS_PATH = Path("data/eval/golden_labels.json")
CACHE_PATH = Path("data/llm_cache/s20_eval.json")
RESULTS_PATH = Path("data/eval/golden_agent_results.json")
NAMESPACE = "s20-eval-v1"
WORST_CASE_CALLS = 7  # planner + (draft + check) x 3 passes


class RecordingRetriever:
    """Passes every search through and keeps a copy of what came back."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.log: list[dict] = []

    def retrieve(self, request):
        response = self.inner.retrieve(request)
        self.log.append({
            "query": request.query,
            "top_k": request.top_k,
            "chunks": [
                {"chunk_id": r.chunk_id, "page_number": r.page_number, "text": r.text}
                for r in response.results
            ],
        })
        return response


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="+")
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--max-requests", type=int, default=40)
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

    base = build_default_retriever(collection_name=f"s20_{uuid.uuid4().hex}")
    base.index_chunks(result.chunks)
    base.retrieve(RetrievalRequest(query="warm up", top_k=config.top_k))
    retriever = RecordingRetriever(base)

    model = os.getenv("OPENROUTER_MODEL") or DEFAULT_MODEL
    if args.replay:
        cache = CachingLLM(CACHE_PATH, None, namespace=NAMESPACE, replay_only=True)
    else:
        cache = CachingLLM(
            CACHE_PATH,
            lambda: OpenRouterLLM.from_env(retries=config.llm_retries),
            namespace=NAMESPACE,
        )
    agent = build_agent(retriever, ShowingLLM(cache), config)

    print(f"GOLDEN AGENT RUN: {'REPLAY' if args.replay else 'LIVE'} | model {model} | namespace {NAMESPACE}")
    results = []
    for q in questions:
        if not args.replay and cache.misses + WORST_CASE_CALLS > args.max_requests:
            print(f"\nStopping before {q['question_id']}: {cache.misses} live calls made, "
                  f"limit {args.max_requests}. Run again later; finished questions replay for free.")
            break

        print(f"\n=== {q['question_id']} [{q['category']}]: {q['question']}")
        print(f"    reference: {q.get('reference_answer') or '(none: unanswerable)'}")
        retriever.log.clear()
        before_misses, before_hits = cache.misses, cache.hits

        final = None
        for event in agent.run_streaming(q["question"]):
            if isinstance(event, AgentResponse):
                final = event
            else:
                show_step(event)

        used, replayed = cache.misses - before_misses, cache.hits - before_hits
        print(f"  ANSWER: {final.answer}")
        print(f"  status: {final.verification_status} | confidence: {final.confidence}")
        for c in final.citations:
            print(f"   [{c.chunk_id} p.{c.page_number}] {c.text_snippet[:90]}")
        print(f"  model calls: {used} live, {replayed} replayed | time: {final.latency_ms / 1000:.1f} s")

        results.append({
            "question_id": q["question_id"],
            "category": q["category"],
            "question": q["question"],
            "reference_answer": q.get("reference_answer", ""),
            "model_calls_live": used,
            "model_calls_replayed": replayed,
            "searches": list(retriever.log),
            "response": final.model_dump(mode="json"),
        })

    print(f"\nTOTAL: {cache.misses} live model calls, {cache.hits} replayed")
    RESULTS_PATH.write_text(json.dumps({
        "run_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "namespace": NAMESPACE,
        "replay": args.replay,
        "config": dataclasses.asdict(config),
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved to", RESULTS_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())