"""What the thresholds did in the golden run (Session 20). 0 requests."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

RESULTS = Path("data/eval/golden_agent_results_full.json")
KEYS = ("top_k", "widened_top_k", "coverage_threshold", "max_confidence", "max_retries")


def main() -> None:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    config = data["config"]
    print("config:", {k: config[k] for k in KEYS})
    print(f"\n{'question':<13}{'status':<10}{'conf':>6}  {'passes':>6}  {'search sizes per pass':<22}coverage per check")

    retried, confidences = 0, []
    for r in data["results"]:
        response = r["response"]
        retrieves = [s for s in response["trace"] if s["step_type"] == "retrieve"]
        checks = [s for s in response["trace"] if s["step_type"] == "fact_check"]
        sizes = [max(s["metadata"].get("chunks_per_search") or [0]) for s in retrieves]
        coverages = [round(s["metadata"]["coverage"], 3) for s in checks if "coverage" in s["metadata"]]
        if len(retrieves) > 1:
            retried += 1
        confidences.append(response["confidence"])
        print(f"{r['question_id']:<13}{response['verification_status']:<10}{response['confidence']:>6}  "
              f"{len(retrieves):>6}  {sizes!s:<22}{coverages}")

    print(f"\nquestions with more than one search pass: {retried} of {len(data['results'])}")
    print("confidence values seen:", sorted(set(confidences)))


if __name__ == "__main__":
    main()