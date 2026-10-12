from pydantic import BaseModel

from app.agents.llm import LLMError
from tests.unit.agents.mocks import MockLLM


class Plan(BaseModel):  # toy stand-in; the real Plan comes with planner.py
    query_type: str
    subqueries: list[str]


llm = MockLLM(
    completions=["draft one", LLMError("timeout")],
    structured={
        Plan: [
            Plan(query_type="simple", subqueries=["q"]),
            {"query_type": "simple"},  # malformed: subqueries missing
        ]
    },
)

print("check 1 - first completion:", llm.complete("sys", "prompt"))

try:
    llm.complete("sys", "prompt")
    print("check 2 - FAILED: no error")
except LLMError as error:
    print("check 2 - scripted failure raised:", error)

try:
    llm.complete("sys", "prompt")
    print("check 3 - FAILED: no error")
except LLMError as error:
    print("check 3 - exhausted raises:", error)

plan = llm.complete_structured("sys", "prompt", Plan)
print("check 4 - structured:", plan.query_type, plan.subqueries)

try:
    llm.complete_structured("sys", "prompt", Plan)
    print("check 5 - FAILED: malformed dict accepted")
except LLMError as error:
    print("check 5 - malformed becomes LLMError:", "not a valid Plan" in str(error))

print("check 6 - total calls recorded:", len(llm.calls))
print("check 7 - complete calls:", len(llm.complete_calls))
print("check 8 - structured calls for Plan:", len(llm.structured_calls(Plan)))