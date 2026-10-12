import pytest
from pydantic import BaseModel

from app.agents.llm import LLMClient, LLMError
from tests.unit.agents.mocks import MockLLM


class Answer(BaseModel):
    text: str
    score: float


class Other(BaseModel):
    n: int


def test_complete_returns_scripted_texts_in_order():
    llm = MockLLM(completions=["first", "second"])
    assert llm.complete("s", "p") == "first"
    assert llm.complete("s", "p") == "second"


def test_complete_with_nothing_left_raises_llm_error():
    llm = MockLLM(completions=["only"])
    llm.complete("s", "p")
    with pytest.raises(LLMError, match="no scripted completion"):
        llm.complete("s", "p")


def test_complete_raises_a_scripted_exception():
    llm = MockLLM(completions=[LLMError("timeout")])
    with pytest.raises(LLMError, match="timeout"):
        llm.complete("s", "p")


def test_structured_returns_scripted_instance():
    llm = MockLLM(structured={Answer: [Answer(text="hi", score=0.5)]})
    result = llm.complete_structured("s", "p", Answer)
    assert result.text == "hi"
    assert result.score == 0.5


def test_structured_validates_a_scripted_dict():
    llm = MockLLM(structured={Answer: [{"text": "hi", "score": 0.5}]})
    result = llm.complete_structured("s", "p", Answer)
    assert isinstance(result, Answer)
    assert result.text == "hi"


def test_structured_invalid_dict_raises_llm_error():
    llm = MockLLM(structured={Answer: [{"text": "hi"}]})  # score missing
    with pytest.raises(LLMError, match="not a valid Answer"):
        llm.complete_structured("s", "p", Answer)


def test_structured_queues_are_separate_per_schema():
    llm = MockLLM(
        structured={
            Answer: [Answer(text="a", score=1.0)],
            Other: [Other(n=7)],
        }
    )
    assert llm.complete_structured("s", "p", Other).n == 7
    assert llm.complete_structured("s", "p", Answer).text == "a"


def test_structured_with_nothing_left_raises_llm_error():
    llm = MockLLM(structured={Answer: []})
    with pytest.raises(LLMError, match="no scripted response left for Answer"):
        llm.complete_structured("s", "p", Answer)


def test_structured_returns_a_copy():
    scripted = Answer(text="original", score=0.5)
    llm = MockLLM(structured={Answer: [scripted]})
    returned = llm.complete_structured("s", "p", Answer)
    returned.text = "EDITED"
    assert scripted.text == "original"


def test_calls_are_recorded_with_details():
    llm = MockLLM(
        completions=["x"],
        structured={Answer: [Answer(text="a", score=1.0)]},
    )
    llm.complete("sys1", "prompt1")
    llm.complete_structured("sys2", "prompt2", Answer)

    first, second = llm.calls
    assert (first.kind, first.system, first.prompt, first.schema) == (
        "complete", "sys1", "prompt1", None
    )
    assert (second.kind, second.system, second.prompt, second.schema) == (
        "structured", "sys2", "prompt2", Answer
    )
    assert len(llm.structured_calls(Answer)) == 1
    assert len(llm.structured_calls(Other)) == 0


def test_structured_only_run_makes_zero_complete_calls():
    llm = MockLLM(structured={Answer: [Answer(text="a", score=1.0)]})
    llm.complete_structured("s", "p", Answer)
    assert llm.complete_calls == []


def test_call_is_recorded_even_when_it_fails():
    llm = MockLLM(completions=[LLMError("boom")])
    with pytest.raises(LLMError):
        llm.complete("s", "p")
    assert len(llm.calls) == 1


def test_mock_llm_satisfies_the_protocol():
    assert isinstance(MockLLM(), LLMClient)