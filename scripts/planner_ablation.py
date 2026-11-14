"""Offline ablation: which part of the planner helps retrieval?

Uses the planner answers cached by measure_planner.py, so it makes NO LLM
requests. If a planner answer is missing from the cache it stops with an error
instead of calling the model.

  python -m scripts.planner_ablation
"""
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.agents.config import AgentConfig
from app.agents.llm_cache import CachingLLM
from app.agents.planner import make_planner_node
from app.agents.retriever_agent import interleave
from app.agents.state import initial_state
from app.retrieval.factory import build_default_retriever
from app.retrieval.metrics import mean, score_against_needs
from app.schemas.retrieval import RetrievalRequest
from scripts.measure_planner import CACHE_PATH, first_rank, found_fraction
from scripts.run_comparison import load_labels_and_chunks

sys.stdout.reconfigure(encoding="utf-8")

TOP_K = 10
METRICS = ["recall@5", "recall@10", "mrr", "ndcg@10"]
VARIANTS = [
    "baseline",
    "full planner",
    "decomposition only",
    "rewrites only",
    "original first",
    "orig + decomp",
    "orig first + decomp",
]
SHORT = {
    "baseline": "base",
    "full planner": "full",
    "decomposition only": "decomp",
    "rewrites only": "rewrites",
    "original first": "orig-first",
    "orig + decomp": "o+decomp",
    "orig first + decomp": "of+decomp",
}
# Numbers this script must reproduce (Member 2's shipped row, Session 14's planner row).
EXPECTED = {
    "baseline": [0.882, 0.912, 0.753, 0.792],
    "full planner": [0.853, 0.912, 0.714, 0.747],
    "decomposition only": [0.912, 0.941, 0.723, 0.765],
    "rewrites only": [0.912, 0.912, 0.776, 0.804],
    "original first": [0.882, 0.912, 0.753, 0.792],
    "orig + decomp": [0.912, 0.912, 0.776, 0.804],
    "orig first + decomp": [0.882, 0.912, 0.753, 0.792],
}
RESULTS_PATH = Path("data/eval/planner_ablation.json")


def norm(text):
    return " ".join(text.lower().split())


def uniq(queries):
    seen, out = set(), []
    for query in queries:
        if norm(query) not in seen:
            seen.add(norm(query))
            out.append(query)
    return out


def no_requests():
    raise RuntimeError(
        "Planner answer not in the cache: this script makes no LLM requests"
    )


def build_variants(text, state, per_query, cap):
    """For one question: variant name -> (number of searches, evidence chunk ids)."""
    original = text.strip()
    subs = state["subqueries"]
    searches = state["search_queries"]
    sub_keys = {norm(s) for s in subs}
    rewrites = [s for s in searches if norm(s) not in sub_keys]
    # the Session 14 planner searched the sub-questions and rewrites, not the original,
    # whenever it split a question
    full = [q for q in searches if norm(original) in sub_keys or norm(q) != norm(original)]

    def merged(queries):
        queries = uniq(queries)
        ids = [c.chunk_id for c in interleave([per_query(q) for q in queries])]
        return len(queries), ids[:cap]

    base_ids = [c.chunk_id for c in per_query(original)]

    def original_first(extra):
        extra = uniq([q for q in extra if norm(q) != norm(original)])
        extra_ids = [c.chunk_id for c in interleave([per_query(q) for q in extra])]
        combined, seen = [], set()
        for chunk_id in base_ids + extra_ids:
            if chunk_id not in seen:
                seen.add(chunk_id)
                combined.append(chunk_id)
        return 1 + len(extra), combined[:cap]

    return {
        "baseline": (1, base_ids),
        "full planner": merged(full),
        "decomposition only": merged(subs),
        "rewrites only": merged([original] + rewrites),
        "original first": original_first(searches),
        "orig + decomp": merged([original] + subs),
        "orig first + decomp": original_first(subs),
    }


def cell(variant):
    if variant["first"] is None:
        return "-"
    return str(variant["first"]) + ("*" if variant["scores"]["recall@10"] < 1 else "")


def table(title, subset):
    print(f"\n{title}")
    print(
        f"{'variant':<22}{'n':>3}{'searches':>10}"
        + "".join(f"{m:>11}" for m in METRICS)
        + f"{'found(20)':>11}{'passages':>10}"
    )
    for name in VARIANTS:
        vs = [r["variants"][name] for r in subset]
        print(
            f"{name:<22}{len(subset):>3}{mean(v['searches'] for v in vs):>10.1f}"
            + "".join(f"{mean(v['scores'][m] for v in vs):>11.3f}" for m in METRICS)
            + f"{mean(v['found'] for v in vs):>11.3f}{mean(v['size'] for v in vs):>10.1f}"
        )


def main():
    if not CACHE_PATH.exists():
        print("No planner cache found at", CACHE_PATH, "- run measure_planner first")
        return

    labels, chunks = load_labels_and_chunks()
    questions = [q for q in labels["questions"] if q["needs"]]

    # rewrites ON here so every variant can be built from the same cached plans;
    # the production default (rewrites off) is the "orig + decomp" variant
    config = AgentConfig(top_k=TOP_K, use_rewrites=True)
    cap = config.max_evidence_chunks
    retriever = build_default_retriever(collection_name=f"ablation_{uuid.uuid4().hex}")
    retriever.index_chunks(chunks)
    retriever.retrieve(RetrievalRequest(query="warm up", top_k=TOP_K))

    memo = {}

    def per_query(query):
        if query not in memo:
            memo[query] = retriever.retrieve(
                RetrievalRequest(query=query, top_k=TOP_K)
            ).results
        return memo[query]

    planner = make_planner_node(CachingLLM(CACHE_PATH, no_requests), config)

    rows = []
    for q in questions:
        needs = [set(n["chunk_ids"]) for n in q["needs"]]
        wanted = set().union(*needs)
        text = q["question"]

        state = initial_state(text, top_k=TOP_K)
        state.update(planner(state))

        variants = {}
        for name, (searches, ids) in build_variants(text, state, per_query, cap).items():
            top = ids[:TOP_K]
            variants[name] = {
                "searches": searches,
                "scores": score_against_needs(top, needs),
                "first": first_rank(top, wanted),
                "found": found_fraction(ids, needs),
                "size": len(ids),
            }
        rows.append(
            {
                "question_id": q["question_id"],
                "category": q["category"],
                "query_type": state["query_type"],
                "changed": state["search_queries"] != [text.strip()],
                "variants": variants,
            }
        )

    changed = [r for r in rows if r["changed"]]
    print(f"PLANNER ABLATION: {len(rows)} questions ({len(changed)} changed by the planner), "
          f"top {TOP_K}, evidence cap {cap}, LLM requests made: 0")

    print("\nSANITY: this script must reproduce earlier numbers")
    for name, expected in EXPECTED.items():
        got = [mean(r["variants"][name]["scores"][m] for r in rows) for m in METRICS]
        ok = all(abs(g - e) < 0.0006 for g, e in zip(got, expected))
        print(f"  {name:<14} {'YES' if ok else 'NO (tell me)'}")

    table(f"ALL {len(rows)} QUESTIONS", rows)
    table(f"ONLY THE {len(changed)} QUESTIONS THE PLANNER CHANGED", changed)

    print("\nFIRST RIGHT CHUNK in the top 10 (changed questions; '-' missed, * not every fact in the top 10)")
    print(f"{'q':<5}{'type':<13}" + "".join(f"{SHORT[name]:>11}" for name in VARIANTS))
    for r in changed:
        print(
            f"{r['question_id']:<5}{r['query_type']:<13}"
            + "".join(f"{cell(r['variants'][name]):>11}" for name in VARIANTS)
        )

    print("\nDecision rule (fixed before running): prefer the variant that finds every fact")
    print("the full planner finds in the full evidence (found(20)), with fewer searches or")
    print("passages, and among those the best top-10 MRR. Same 17 questions Member 2 tuned")
    print("on, so this informs a decision; it does not prove anything.")

    RESULTS_PATH.write_text(
        json.dumps(
            {
                "run_at": datetime.now(UTC).isoformat(),
                "top_k": TOP_K,
                "evidence_cap": cap,
                "llm_requests_made": 0,
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