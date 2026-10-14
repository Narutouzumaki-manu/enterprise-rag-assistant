"""Does the planner help retrieval?  Compares 'original question only' with
'the planner's searches' on the real TCS index and Member 2's labels.

  python -m scripts.measure_planner --only q16 q19   first look (about 2 requests)
  python -m scripts.measure_planner                  all answerable questions

Planner answers are cached in data/eval/planner_cache.json, so a rerun costs
no requests. Same protocol as final_check.py: top 10, same scoring.
"""
import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.agents.config import AgentConfig
from app.agents.llm import OpenRouterLLM
from app.agents.planner import make_planner_node
from app.agents.retriever_agent import make_retriever_node
from app.agents.state import initial_state
from app.retrieval.factory import build_default_retriever
from app.retrieval.metrics import mean, score_against_needs
from app.schemas.retrieval import RetrievalRequest
from scripts.run_comparison import load_labels_and_chunks

sys.stdout.reconfigure(encoding="utf-8")

TOP_K = 10
METRICS = ["recall@5", "recall@10", "mrr", "ndcg@10"]
CACHE_PATH = Path("data/eval/planner_cache.json")
RESULTS_PATH = Path("data/eval/planner_measurement.json")


class CachingLLM:
    """Replays saved planner answers; calls the real model only on a miss."""

    def __init__(self, path, make_inner):
        self.path = path
        self.make_inner = make_inner
        self.inner = None
        self.calls = 0
        self.cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def complete(self, system, prompt):
        raise NotImplementedError("this script only makes structured calls")

    def complete_structured(self, system, prompt, schema):
        key = hashlib.sha256(
            f"{schema.__name__}\n{system}\n{prompt}".encode("utf-8")
        ).hexdigest()
        if key in self.cache:
            return schema.model_validate(self.cache[key])
        if self.inner is None:
            self.inner = self.make_inner()
        self.calls += 1
        result = self.inner.complete_structured(system, prompt, schema)  # failures are not cached
        self.cache[key] = result.model_dump()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result


def first_rank(ranked, wanted):
    return next((p for p, cid in enumerate(ranked, 1) if cid in wanted), None)


def found_fraction(ids, needs):
    present = set(ids)
    return sum(1 for need in needs if need & present) / len(needs)


def cell(first, scores):
    if first is None:
        return "-"
    return str(first) + ("*" if scores["recall@10"] < 1 else "")


def averages(rows, key):
    return {m: mean(r[key][m] for r in rows) for m in METRICS}


def line(label, rows, key):
    a = averages(rows, key)
    return f"{label:<22}{len(rows):>4}" + "".join(f"{a[m]:>11.3f}" for m in METRICS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="+", help="question ids, for example q16 q19")
    args = parser.parse_args()

    labels, chunks = load_labels_and_chunks()
    questions = [q for q in labels["questions"] if q["needs"]]
    if args.only:
        questions = [q for q in questions if q["question_id"] in set(args.only)]
        if not questions:
            print("No answerable question matches", args.only)
            return

    config = AgentConfig(top_k=TOP_K)
    retriever = build_default_retriever(collection_name=f"planner_{uuid.uuid4().hex}")
    retriever.index_chunks(chunks)
    retriever.retrieve(RetrievalRequest(query="warm up", top_k=TOP_K))

    llm = CachingLLM(
        CACHE_PATH, lambda: OpenRouterLLM.from_env(retries=config.llm_retries)
    )
    planner = make_planner_node(llm, config)
    fetch = make_retriever_node(retriever, config)

    rows = []
    for q in questions:
        needs = [set(n["chunk_ids"]) for n in q["needs"]]
        wanted = set().union(*needs)
        text = q["question"]

        base_ranked = [
            r.chunk_id
            for r in retriever.retrieve(RetrievalRequest(query=text, top_k=TOP_K)).results
        ]

        state = initial_state(text, top_k=TOP_K)
        state.update(planner(state))
        full_evidence = [c.chunk_id for c in fetch(state)["retrieved_chunks"]]
        plan_ranked = full_evidence[:TOP_K]

        base_scores = score_against_needs(base_ranked, needs)
        plan_scores = score_against_needs(plan_ranked, needs)
        rows.append(
            {
                "question_id": q["question_id"],
                "category": q["category"],
                "style": q["style"],
                "query_type": state["query_type"],
                "searches": state["search_queries"],
                "changed": state["search_queries"] != [text.strip()],
                "fallback": bool(state["trace"][0].metadata.get("fallback")),
                "base_scores": base_scores,
                "plan_scores": plan_scores,
                "base_first": first_rank(base_ranked, wanted),
                "plan_first": first_rank(plan_ranked, wanted),
                "base_found": found_fraction(base_ranked, needs),
                "plan_found_full": found_fraction(full_evidence, needs),
                "plan_size": len(full_evidence),
            }
        )

    changed = [r for r in rows if r["changed"]]
    unchanged = [r for r in rows if not r["changed"]]

    print(f"PLANNER MEASUREMENT: {len(rows)} questions, top {TOP_K}, LLM calls made now: {llm.calls}")
    print(f"planner fell back on {sum(r['fallback'] for r in rows)} question(s)")

    print("\nPER QUESTION (position of the first right chunk, '-' = missed, * = not every fact found)")
    print(f"{'q':<5}{'category':<13}{'type':<13}{'searches':>9}{'baseline':>10}{'planner':>9}")
    for r in rows:
        print(
            f"{r['question_id']:<5}{r['category']:<13}{r['query_type']:<13}"
            f"{len(r['searches']):>9}"
            f"{cell(r['base_first'], r['base_scores']):>10}"
            f"{cell(r['plan_first'], r['plan_scores']):>9}"
        )

    if changed:
        print("\nSEARCHES SENT WHEN THE PLANNER CHANGED SOMETHING")
        for r in changed:
            print(f"{r['question_id']} ({r['category']}, {r['query_type']}):")
            for i, text in enumerate(r["searches"], 1):
                print(f"   {i}. {text}")

    header = f"{'':<22}{'n':>4}" + "".join(f"{m:>11}" for m in METRICS)
    print("\nOVERALL (first 10 of each ranking, same size)")
    print(header)
    print(line("baseline", rows, "base_scores"))
    print(line("planner searches", rows, "plan_scores"))

    print("\nSANITY: questions the planner left unchanged must score exactly as the baseline")
    same = all(r["base_scores"] == r["plan_scores"] for r in unchanged)
    print(f"  unchanged questions: {len(unchanged)} | identical scores: {'YES' if same else 'NO (tell me)'}")

    if changed:
        print("\nONLY THE QUESTIONS THE PLANNER CHANGED")
        print(header)
        print(line("baseline", changed, "base_scores"))
        print(line("planner searches", changed, "plan_scores"))
        better = sum(r["plan_scores"]["mrr"] > r["base_scores"]["mrr"] for r in changed)
        worse = sum(r["plan_scores"]["mrr"] < r["base_scores"]["mrr"] for r in changed)
        print(f"  MRR better on {better}, worse on {worse}, same on {len(changed) - better - worse}")

        print("\nFULL EVIDENCE the synthesizer would receive (planner path keeps up to 20 passages)")
        print(f"  baseline (top {TOP_K}): facts found {mean(r['base_found'] for r in changed):.3f} | passages {TOP_K}")
        print(
            f"  planner path        : facts found {mean(r['plan_found_full'] for r in changed):.3f} "
            f"| passages {mean(r['plan_size'] for r in changed):.1f} on average"
        )
        print("  (more passages mean more cost and more noise for the generator)")
    else:
        print("\nThe planner added no extra searches on these questions.")

    print("\nNOTES: same 17 questions Member 2 tuned on; planner output varies between live")
    print("runs (the cache makes reruns identical); a signal to act on, not a proof.")

    RESULTS_PATH.write_text(
        json.dumps(
            {
                "run_at": datetime.now(timezone.utc).isoformat(),
                "top_k": TOP_K,
                "questions": len(rows),
                "llm_calls_made": llm.calls,
                "per_question": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("\nsaved to", RESULTS_PATH)


if __name__ == "__main__":
    main()