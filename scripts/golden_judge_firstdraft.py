"""Would the independent judge also have flagged the claim the fact-checker removed? (Session 20)
1 live call.

  python -m scripts.golden_judge_firstdraft
  python -m scripts.golden_judge_firstdraft --replay
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
    MAX_CONTEXT,
    SYSTEM_PROMPT,
    JudgeResult,
    build_prompt,
)

sys.stdout.reconfigure(encoding="utf-8")

QUESTION_ID = "tcs-gold-08"
# Copied from the console output of the full run (the agent's FIRST draft for gold-08).
FIRST_DRAFT = (
    "The report ties TCS's AI strategy to employee development by presenting reskilling "
    "the workforce as a strategic priority, noting that AI proficiency and learning hours "
    "are outcomes of its AI-led transformation. The two FY26 training figures that support "
    "this connection are 69 million learning hours (up 23% year-on-year) and 270,000+ "
    "employees with higher proficiency in AI/ML."
)
FLAGGED_TOKEN = "outcomes"  # the claim Nemotron's fact-checker marked unsupported


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", action="store_true")
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
    item = next(r for r in data["results"] if r["question_id"] == QUESTION_ID)

    # Only the searches of the FIRST pass: the evidence the first draft was written from.
    first_retrieve = next(s for s in item["response"]["trace"] if s["step_type"] == "retrieve")
    first_pass_searches = first_retrieve["metadata"]["search_query_count"]
    seen, contexts = set(), []
    for search in item["searches"][:first_pass_searches]:
        for chunk in search["chunks"]:
            if chunk["chunk_id"] not in seen:
                seen.add(chunk["chunk_id"])
                contexts.append(chunk)
    contexts = contexts[:MAX_CONTEXT]
    print(f"first pass: {first_pass_searches} searches, {len(contexts)} passages "
          f"(the trace said {first_retrieve['content']!r})")

    print(f"JUDGE: {'REPLAY' if args.replay else 'LIVE'} | model {JUDGE_MODEL} | namespace {JUDGE_NAMESPACE}")
    try:
        result = cache.complete_structured(
            SYSTEM_PROMPT, build_prompt(item["question"], FIRST_DRAFT, contexts), JudgeResult
        )
    except LLMError as error:
        print(f"JUDGE ERROR: {error}")
        return 1

    for s in result.statements:
        print(f"  {'supported    ' if s.supported else 'NOT supported'}  {s.statement} ({s.reason})")
    flagged = [s for s in result.statements if FLAGGED_TOKEN in s.statement.lower()]
    if not flagged:
        print("-> NOT FOUND: no statement contains the flagged claim; read it by hand")
    elif all(not s.supported for s in flagged):
        print("-> the judge AGREES with the fact-checker: the claim is not supported")
    else:
        print("-> the judge DISAGREES with the fact-checker: it accepts the claim")
    print(f"TOTAL: {cache.misses} live calls, {cache.hits} replayed")
    return 0


if __name__ == "__main__":
    sys.exit(main())