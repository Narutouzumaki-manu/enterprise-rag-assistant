import json
import tempfile
from pathlib import Path

from pydantic import BaseModel

from app.agents.llm import LLMError
from app.agents.llm_cache import CachingLLM
from tests.unit.agents.mocks import MockLLM


class Answer(BaseModel):
    text: str


path = Path(tempfile.mkdtemp()) / "cache.json"
inner = MockLLM(structured={Answer: [Answer(text="first answer")]})
llm = CachingLLM(path, inner)

a = llm.complete_structured("sys", "question", Answer)
print("check 1 - first call:", a.text, "| real calls:", llm.misses, "| hits:", llm.hits)

b = llm.complete_structured("sys", "question", Answer)
print("check 2 - repeat call:", b.text, "| real calls:", llm.misses, "| hits:", llm.hits)

empty = MockLLM()  # a model that has nothing to say
fresh = CachingLLM(path, empty)
c = fresh.complete_structured("sys", "question", Answer)
print("check 3 - new instance replays from the file:", c.text, "| model calls:", len(empty.calls))

strict = CachingLLM(path, MockLLM(), replay_only=True)
try:
    strict.complete_structured("sys", "a different question", Answer)
    print("check 4 - FAILED: no error")
except LLMError as error:
    print("check 4 - replay-only miss raises:", error)

print("check 5 - entries on disk:", len(json.loads(path.read_text(encoding="utf-8"))))