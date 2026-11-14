"""Checks the Member 3 documents against the real code (mechanical facts only).

  python -m scripts.check_docs_against_code            documents in ./docs
  python -m scripts.check_docs_against_code --docs path

Checked:
  - Backend Schema: AgentState keys; Plan, Draft, ClaimVerdict and Verification fields;
    AgentConfig fields and defaults
  - UI/UX: the exact answer texts and terminal trace texts the agent emits
  - all four documents carry the version v0.3
Not checked here: prose claims (behaviour, numbers). Those are checked against the
tests and runs listed in the Session 19 log.
"""
import argparse
import ast
import dataclasses
import re
import sys
from pathlib import Path

from app.agents.agent import EMPTY_QUERY_ANSWER
from app.agents.config import AgentConfig
from app.agents.fact_checker import ClaimVerdict, Verification
from app.agents.planner import Plan
from app.agents.state import AgentState
from app.agents.synthesizer import (
    _TERMINAL,
    GENERATION_FAILED_ANSWER,
    NO_EVIDENCE_ANSWER,
    SEARCH_FAILED_ANSWER,
    Draft,
)

DOCS = {
    "PRD": "PRD_Member3_Agents.md",
    "TRD": "TRD_Member3_Agents.md",
    "Backend Schema": "Backend_Schema_Member3_Agents.md",
    "UI/UX": "UIUX_Member3_Agents.md",
}
VERSION = "v0.3"
EXTRA_PHRASES = [
    "The passages do not contain the answer; searching again",
    "Could not be verified in the documents:",
    "removed because it contains instructions",
]


def python_blocks(text: str) -> list[str]:
    return re.findall(r"```python\n(.*?)```", text, re.DOTALL)


def class_body(text: str, class_name: str) -> list[str] | None:
    """Indented lines of `class <class_name>` in any python code block of the document."""
    for block in python_blocks(text):
        lines = block.splitlines()
        for index, line in enumerate(lines):
            if re.match(rf"class {class_name}\b", line):
                body = []
                for follow in lines[index + 1:]:
                    if follow.strip() and not follow.startswith(" "):
                        break
                    body.append(follow)
                return body
    return None


def field_names(body: list[str]) -> list[str]:
    return [m.group(1) for line in body if (m := re.match(r"^ {4}(\w+)\s*:", line))]


def field_defaults(body: list[str]) -> dict:
    out = {}
    for line in body:
        m = re.match(r"^ {4}(\w+)\s*:\s*[^=#]+=\s*([^#]+?)\s*(?:#.*)?$", line)
        if m:
            out[m.group(1)] = ast.literal_eval(m.group(2))
    return out


def compare_names(label: str, doc_names: list[str], real_names: list[str], problems: list[str]) -> None:
    missing = [n for n in real_names if n not in doc_names]
    extra = [n for n in doc_names if n not in real_names]
    if missing or extra:
        problems.append(f"{label}: missing in the document {missing}, not in the code {extra}")
    else:
        print(f"  OK  {label}: {len(real_names)} fields match")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", default="docs")
    args = parser.parse_args()
    folder = Path(args.docs)

    texts, problems = {}, []
    for label, name in DOCS.items():
        path = folder / name
        if not path.exists():
            problems.append(f"{label}: file not found: {path}")
            continue
        texts[label] = path.read_text(encoding="utf-8")
        if VERSION in texts[label]:
            print(f"  OK  {label}: carries {VERSION}")
        else:
            problems.append(f"{label}: does not mention {VERSION}")

    schema = texts.get("Backend Schema")
    if schema:
        checks = [("AgentState", list(AgentState.__annotations__))]
        for model in (Plan, Draft, ClaimVerdict, Verification):
            checks.append((model.__name__, list(model.model_fields)))
        for name, real in checks:
            body = class_body(schema, name)
            if body is None:
                problems.append(f"{name}: no code block in the Backend Schema")
            else:
                compare_names(name, field_names(body), real, problems)

        body = class_body(schema, "AgentConfig")
        if body is None:
            problems.append("AgentConfig: no code block in the Backend Schema")
        else:
            real = {f.name: f.default for f in dataclasses.fields(AgentConfig)}
            compare_names("AgentConfig", field_names(body), list(real), problems)
            documented = field_defaults(body)
            wrong = {n: (documented.get(n), v) for n, v in real.items() if documented.get(n) != v}
            if wrong:
                problems.append(f"AgentConfig defaults differ (document, code): {wrong}")
            else:
                print(f"  OK  AgentConfig: {len(real)} defaults match")

    uiux = texts.get("UI/UX")
    if uiux:
        required = [NO_EVIDENCE_ANSWER, SEARCH_FAILED_ANSWER, GENERATION_FAILED_ANSWER, EMPTY_QUERY_ANSWER]
        required += [content for _answer, content, _called in _TERMINAL.values()]
        required += EXTRA_PHRASES
        missing = [p for p in required if p not in uiux]
        if missing:
            problems.append(f"UI/UX is missing texts the agent emits: {missing}")
        else:
            print(f"  OK  UI/UX: all {len(required)} agent texts appear")

    print()
    if problems:
        print("PROBLEMS:")
        for problem in problems:
            print("  -", problem)
        return 1
    print("All mechanical checks pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())