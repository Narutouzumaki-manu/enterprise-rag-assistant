"""Does the judge catch planted errors? (Session 20) 3 live calls.

  python -m scripts.golden_judge_check
  python -m scripts.golden_judge_check --replay
"""
import argparse
import json
import os
import sys

from dotenv import load_dotenv

from app.agents.llm import LLMError, OpenRouterLLM
from app.agents.llm_cache import CachingLLM
from scripts.golden_judge_eval import (
    AGENT_RESULTS,
    JUDGE_CACHE,
    JUDGE_MODEL,
    JUDGE_NAMESPACE,
    SYSTEM_PROMPT,
    JudgeResult,
    agent_contexts,
    build_prompt,
)

sys.stdout.reconfigure(encoding="utf-8")

PLANTED = [
    {"question_id": "tcs-gold-02", "kind": "wrong figure",
     "answer": "TCS's FY26 operating margin was 27% and net margin was 19.8%.",
     "tokens": ["27%"]},
    {"question_id": "tcs-gold-04", "kind": "figures from the wrong year",
     "answer": "FY26 total TCV: $40.7 billion; North America TCV: $21.6 billion; Consumer Business TCV: $5.3 billion.",
     "tokens": ["21.6", "5.3"]},
    {"question_id": "tcs-gold-06", "kind": "invented fact",
     "answer": "TCS's total contract value in Q4 FY26 was $12 billion, driven mainly by a record order from a European bank.",
     "tokens": ["european bank", "record order"]},
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--max-requests", type=int, default=3)
    args = parser.parse_args()

    load_dotenv()
    if os.getenv("OPENROUTER_MODEL") == JUDGE_MODEL:
        print("STOP: the generator model equals the judge model.")
        return 1
    os.environ["OPENROUTER_MODEL"] = JUDGE_MODEL
    os.environ.pop("OPENROUTER_FALLBACK_MODELS", None)

    if args.replay:
        cache = CachingLLM(JUDGE_CACHE, None, namespace=JUDGE_NAMESPACE, replay_only=True)
    else:
        cache = CachingLLM(JUDGE_CACHE, lambda: OpenRouterLLM.from_env(retries=1), namespace=JUDGE_NAMESPACE)

    data = json.loads(AGENT_RESULTS.read_text(encoding="utf-8"))
    by_id = {r["question_id"]: r for r in data["results"]}

    print(f"JUDGE CHECK: {'REPLAY' if args.replay else 'LIVE'} | model {JUDGE_MODEL} | namespace {JUDGE_NAMESPACE}")
    caught = 0
    for case in PLANTED:
        item = by_id[case["question_id"]]
        print(f"\n=== {case['question_id']} planted: {case['kind']}")
        print(f"    answer: {case['answer']}")
        if not args.replay and cache.misses + 1 > args.max_requests:
            print("   stopping: request limit reached")
            return 1
        try:
            result = cache.complete_structured(
                SYSTEM_PROMPT,
                build_prompt(item["question"], case["answer"], agent_contexts(item)),
                JudgeResult,
            )
        except LLMError as error:
            print(f"   JUDGE ERROR: {error}")
            return 1
        for s in result.statements:
            print(f"   {'supported    ' if s.supported else 'NOT supported'}  {s.statement} ({s.reason})")
        hits = [s for s in result.statements
                if any(t in s.statement.lower() for t in case["tokens"])]
        if not hits:
            verdict = "NOT FOUND: no statement contains the planted detail; read it by hand"
        elif all(not s.supported for s in hits):
            verdict = "CAUGHT"
            caught += 1
        else:
            verdict = "MISSED"
        print(f"   -> {verdict}")

    print(f"\nTOTAL: caught {caught} of {len(PLANTED)} | {cache.misses} live calls, {cache.hits} replayed")
    return 0


if __name__ == "__main__":
    sys.exit(main())