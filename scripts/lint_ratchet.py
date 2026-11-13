"""Lint and type-check ratchet.

Ensures that new code does not introduce new lint or type errors by comparing
current Ruff and Mypy findings against a frozen baseline (lint_baseline.json).
"""

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

BASELINE_FILE = Path("lint_baseline.json")


def get_ruff_version() -> str:
    """Return installed Ruff version string (e.g. '0.17.5')."""
    res = subprocess.run(
        [sys.executable, "-m", "ruff", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip().split()[-1]


def get_mypy_version() -> str:
    """Return installed Mypy version string (e.g. '2.4.1')."""
    res = subprocess.run(
        [sys.executable, "-m", "mypy", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip().split()[1]


def run_ruff_check() -> dict[str, int]:
    """Run Ruff and count findings per rule code."""
    res = subprocess.run(
        [sys.executable, "-m", "ruff", "check", ".", "--output-format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    data = json.loads(res.stdout) if res.stdout.strip() else []
    counts: dict[str, int] = {}
    for item in data:
        code = item["code"]
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def run_mypy_check() -> dict[str, int]:
    """Run Mypy and count errors per normalized file path."""
    res = subprocess.run(
        [sys.executable, "-m", "mypy", "app", "--show-error-codes"],
        capture_output=True,
        text=True,
        check=False,
    )
    counts: dict[str, int] = {}
    for line in res.stdout.splitlines():
        m = re.match(r"^([^:]+):\d+(?::\d+)?: error:", line)
        if m:
            file_path = m.group(1).strip().replace("\\", "/")
            counts[file_path] = counts.get(file_path, 0) + 1
    return dict(sorted(counts.items()))


def compare_lint_and_type(
    current: dict,
    baseline: dict,
    simulate_extra: int = 0,
) -> tuple[bool, list[str], list[str]]:
    """Compare current findings against baseline.

    Returns:
        (passed, error_messages, improvement_messages)
    """
    errors: list[str] = []
    improvements: list[str] = []

    # 1. Check tool versions
    cur_ruff_ver = current.get("ruff_version")
    base_ruff_ver = baseline.get("ruff_version")
    if cur_ruff_ver != base_ruff_ver:
        errors.append(
            f"Ruff version mismatch: current {cur_ruff_ver} != baseline {base_ruff_ver}"
        )

    cur_mypy_ver = current.get("mypy_version")
    base_mypy_ver = baseline.get("mypy_version")
    if cur_mypy_ver != base_mypy_ver:
        errors.append(
            f"Mypy version mismatch: current {cur_mypy_ver} != baseline {base_mypy_ver}"
        )

    # Copy current ruff rules for comparison
    cur_ruff_rules = dict(current.get("ruff_rules", {}))
    base_ruff_rules = baseline.get("ruff_rules", {})

    # Apply simulation option if requested
    if simulate_extra > 0:
        if cur_ruff_rules:
            first_rule = min(cur_ruff_rules.keys())
            cur_ruff_rules[first_rule] += simulate_extra
            print(
                f"[SIMULATE] Added {simulate_extra} to rule {first_rule} (simulated total: {cur_ruff_rules[first_rule]})"
            )
        else:
            cur_ruff_rules["SIMULATED"] = simulate_extra
            print(f"[SIMULATE] Added {simulate_extra} to new rule SIMULATED")

    # 2. Compare Ruff rules
    for rule, count in sorted(cur_ruff_rules.items()):
        if rule not in base_ruff_rules:
            errors.append(f"New Ruff rule violation: {rule} ({count} finding(s))")
        elif count > base_ruff_rules[rule]:
            diff = count - base_ruff_rules[rule]
            errors.append(
                f"Ruff rule {rule} count increased: {count} > {base_ruff_rules[rule]} (+{diff})"
            )
        elif count < base_ruff_rules[rule]:
            diff = base_ruff_rules[rule] - count
            improvements.append(
                f"Ruff rule {rule} decreased: {base_ruff_rules[rule]} -> {count} (-{diff})"
            )

    for rule, base_count in sorted(base_ruff_rules.items()):
        if rule not in cur_ruff_rules:
            improvements.append(
                f"Ruff rule {rule} eliminated: {base_count} -> 0 (-{base_count})"
            )

    # 3. Compare Mypy per-file errors
    cur_mypy_files = current.get("mypy_files", {})
    base_mypy_files = baseline.get("mypy_files", {})

    for file_path, count in sorted(cur_mypy_files.items()):
        if file_path not in base_mypy_files:
            errors.append(f"New file with Mypy errors: {file_path} ({count} error(s))")
        elif count > base_mypy_files[file_path]:
            diff = count - base_mypy_files[file_path]
            errors.append(
                f"Mypy errors in {file_path} increased: {count} > {base_mypy_files[file_path]} (+{diff})"
            )
        elif count < base_mypy_files[file_path]:
            diff = base_mypy_files[file_path] - count
            improvements.append(
                f"Mypy errors in {file_path} decreased: {base_mypy_files[file_path]} -> {count} (-{diff})"
            )

    for file_path, base_count in sorted(base_mypy_files.items()):
        if file_path not in cur_mypy_files:
            improvements.append(
                f"Mypy errors in {file_path} eliminated: {base_count} -> 0 (-{base_count})"
            )

    passed = len(errors) == 0
    return passed, errors, improvements


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint and Type-check Ratchet")
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Write current ruff and mypy findings to lint_baseline.json",
    )
    parser.add_argument(
        "--simulate-extra",
        type=int,
        default=0,
        metavar="N",
        help="Add N to one ruff rule's count to simulate a regression",
    )
    args = parser.parse_args()

    print("Checking tool versions...")
    ruff_ver = get_ruff_version()
    mypy_ver = get_mypy_version()
    print(f"Ruff: {ruff_ver}, Mypy: {mypy_ver}")

    print("Running Ruff check...")
    ruff_counts = run_ruff_check()
    total_ruff = sum(ruff_counts.values())
    print(f"Ruff findings: {total_ruff} across {len(ruff_counts)} rules")

    print("Running Mypy check...")
    mypy_counts = run_mypy_check()
    total_mypy = sum(mypy_counts.values())
    print(f"Mypy errors: {total_mypy} across {len(mypy_counts)} files")

    current_data = {
        "date": datetime.date.today().isoformat(),
        "ruff_version": ruff_ver,
        "mypy_version": mypy_ver,
        "ruff_rules": ruff_counts,
        "mypy_files": mypy_counts,
    }

    if args.write_baseline:
        with open(BASELINE_FILE, "w", encoding="utf-8") as f:
            json.dump(current_data, f, indent=2)
            f.write("\n")
        print(f"Wrote baseline to {BASELINE_FILE} successfully.")
        return 0

    if not BASELINE_FILE.exists():
        print(
            f"ERROR: Baseline file {BASELINE_FILE} does not exist. Run with --write-baseline first.",
            file=sys.stderr,
        )
        return 1

    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
        baseline_data = json.load(f)

    passed, errors, improvements = compare_lint_and_type(
        current_data,
        baseline_data,
        simulate_extra=args.simulate_extra,
    )

    if improvements:
        print("\n--- Improved findings (counts went down; baseline can be lowered) ---")
        for item in improvements:
            print(f"  [IMPROVED] {item}")

    if not passed:
        print("\n--- LINT RATCHET REGRESSIONS DETECTED ---", file=sys.stderr)
        for err in errors:
            print(f"  [FAIL] {err}", file=sys.stderr)
        return 1

    print("\nLint and type ratchet check passed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
