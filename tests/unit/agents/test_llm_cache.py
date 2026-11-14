import hashlib
import json
import threading

import pytest
from pydantic import BaseModel

from app.agents.llm import LLMClient, LLMError
from app.agents.llm_cache import CachingLLM
from tests.unit.agents.mocks import MockLLM


class Answer(BaseModel):
    text: str


class Other(BaseModel):
    n: int


def make(tmp_path, structured=None, completions=None, **kwargs):
    inner = MockLLM(structured=structured, completions=completions)
    return CachingLLM(tmp_path / "cache.json", inner, **kwargs), inner


def test_miss_calls_the_inner_model_and_saves_the_answer(tmp_path):
    llm, inner = make(tmp_path, structured={Answer: [Answer(text="a")]})
    assert llm.complete_structured("sys", "q", Answer) == Answer(text="a")
    assert (llm.misses, llm.hits) == (1, 0)
    assert len(inner.calls) == 1
    assert json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))


def test_hit_replays_without_calling_the_inner_model(tmp_path):
    llm, inner = make(tmp_path, structured={Answer: [Answer(text="a")]})
    llm.complete_structured("sys", "q", Answer)
    second = llm.complete_structured("sys", "q", Answer)
    assert second == Answer(text="a")
    assert len(inner.calls) == 1
    assert (llm.misses, llm.hits) == (1, 1)


def test_cache_survives_a_new_instance(tmp_path):
    llm, _ = make(tmp_path, structured={Answer: [Answer(text="a")]})
    llm.complete_structured("sys", "q", Answer)
    empty = MockLLM()
    fresh = CachingLLM(tmp_path / "cache.json", empty)
    assert fresh.complete_structured("sys", "q", Answer) == Answer(text="a")
    assert empty.calls == []


def test_different_inputs_are_separate_entries(tmp_path):
    llm, inner = make(
        tmp_path,
        structured={
            Answer: [Answer(text="1"), Answer(text="2"), Answer(text="3")],
            Other: [Other(n=4)],
        },
    )
    llm.complete_structured("sys", "q", Answer)
    llm.complete_structured("sys", "q2", Answer)
    llm.complete_structured("sys2", "q", Answer)
    llm.complete_structured("sys", "q", Other)
    assert llm.misses == 4
    assert len(inner.calls) == 4


def test_plain_complete_is_cached_too(tmp_path):
    llm, inner = make(tmp_path, completions=["hello"])
    assert llm.complete("sys", "q") == "hello"
    assert llm.complete("sys", "q") == "hello"
    assert len(inner.calls) == 1
    assert (llm.misses, llm.hits) == (1, 1)
    empty = MockLLM()
    assert CachingLLM(tmp_path / "cache.json", empty).complete("sys", "q") == "hello"
    assert empty.calls == []


def test_failures_are_not_cached(tmp_path):
    llm, inner = make(
        tmp_path, structured={Answer: [LLMError("down"), Answer(text="ok")]}
    )
    with pytest.raises(LLMError):
        llm.complete_structured("sys", "q", Answer)
    assert llm.misses == 1
    assert llm.complete_structured("sys", "q", Answer) == Answer(text="ok")
    assert llm.misses == 2
    assert llm.complete_structured("sys", "q", Answer) == Answer(text="ok")
    assert llm.hits == 1
    assert len(inner.calls) == 2


def test_replay_only_raises_on_a_miss(tmp_path):
    llm, inner = make(tmp_path, replay_only=True)
    with pytest.raises(LLMError, match="replay-only"):
        llm.complete_structured("sys", "q", Answer)
    assert inner.calls == []
    assert llm.misses == 0


def test_replay_only_still_serves_hits(tmp_path):
    first, _ = make(tmp_path, structured={Answer: [Answer(text="a")]})
    first.complete_structured("sys", "q", Answer)
    empty = MockLLM()
    strict = CachingLLM(tmp_path / "cache.json", empty, replay_only=True)
    assert strict.complete_structured("sys", "q", Answer) == Answer(text="a")
    assert empty.calls == []


def test_namespace_separates_entries(tmp_path):
    path = tmp_path / "cache.json"
    inner_a = MockLLM(structured={Answer: [Answer(text="v1")]})
    inner_b = MockLLM(structured={Answer: [Answer(text="v2")]})
    a = CachingLLM(path, inner_a, namespace="v1")
    b = CachingLLM(path, inner_b, namespace="v2")
    assert a.complete_structured("sys", "q", Answer).text == "v1"
    assert b.complete_structured("sys", "q", Answer).text == "v2"
    assert len(inner_b.calls) == 1
    again = CachingLLM(path, MockLLM(), namespace="v1")
    assert again.complete_structured("sys", "q", Answer).text == "v1"


def test_default_key_matches_the_old_throwaway_cache(tmp_path):
    system, prompt = "sys", "q"
    key = hashlib.sha256(f"Answer\n{system}\n{prompt}".encode()).hexdigest()
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({key: {"text": "old"}}), encoding="utf-8")
    empty = MockLLM()
    llm = CachingLLM(path, empty)
    assert llm.complete_structured(system, prompt, Answer) == Answer(text="old")
    assert empty.calls == []


def test_lazy_inner_factory_is_only_called_on_a_miss(tmp_path):
    path = tmp_path / "cache.json"
    built = []
    inner = MockLLM(structured={Answer: [Answer(text="a"), Answer(text="b")]})

    def factory():
        built.append(1)
        return inner

    llm = CachingLLM(path, factory)
    assert built == []
    llm.complete_structured("sys", "q1", Answer)
    assert built == [1]
    llm.complete_structured("sys", "q1", Answer)
    llm.complete_structured("sys", "q2", Answer)
    assert built == [1]
    assert len(inner.calls) == 2

    built.clear()
    cached = CachingLLM(path, factory)
    cached.complete_structured("sys", "q1", Answer)
    assert built == []


def test_stale_entry_for_an_older_schema_is_a_miss(tmp_path):
    key = hashlib.sha256(b"Answer\nsys\nq").hexdigest()
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({key: {"wrong": 1}}), encoding="utf-8")
    inner = MockLLM(structured={Answer: [Answer(text="fresh")]})
    llm = CachingLLM(path, inner)
    assert llm.complete_structured("sys", "q", Answer) == Answer(text="fresh")
    assert len(inner.calls) == 1
    assert json.loads(path.read_text(encoding="utf-8"))[key] == {"text": "fresh"}


def test_corrupt_file_raises_a_clear_error(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        CachingLLM(path, MockLLM())


def test_non_object_file_raises_a_clear_error(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        CachingLLM(path, MockLLM())


def test_returned_object_is_a_copy(tmp_path):
    llm, _ = make(tmp_path, structured={Answer: [Answer(text="a")]})
    first = llm.complete_structured("sys", "q", Answer)
    first.text = "EDITED"
    assert llm.complete_structured("sys", "q", Answer).text == "a"


def test_creates_parent_folders(tmp_path):
    path = tmp_path / "a" / "b" / "cache.json"
    inner = MockLLM(structured={Answer: [Answer(text="a")]})
    CachingLLM(path, inner).complete_structured("sys", "q", Answer)
    assert path.exists()


def test_calls_property_counts_real_calls(tmp_path):
    llm, _ = make(tmp_path, structured={Answer: [Answer(text="a")]})
    llm.complete_structured("sys", "q", Answer)
    llm.complete_structured("sys", "q", Answer)
    assert llm.calls == 1


def test_satisfies_the_protocol(tmp_path):
    llm, _ = make(tmp_path)
    assert isinstance(llm, LLMClient)


def test_concurrent_calls_keep_the_cache_file_valid(tmp_path):
    inner = MockLLM(structured={Answer: [Answer(text=str(i)) for i in range(20)]})
    llm = CachingLLM(tmp_path / "cache.json", inner)
    errors = []

    def worker(i):
        try:
            llm.complete_structured("sys", f"question {i}", Answer)
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    data = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
    assert len(data) == 20
    assert llm.misses == 20

def test_two_instances_on_one_file_keep_each_others_entries(tmp_path):
    path = tmp_path / "cache.json"
    a = CachingLLM(path, MockLLM(structured={Answer: [Answer(text="from a")]}))
    b = CachingLLM(path, MockLLM(structured={Answer: [Answer(text="from b")]}))
    # both loaded the (empty) file before either wrote to it
    a.complete_structured("sys", "question a", Answer)
    b.complete_structured("sys", "question b", Answer)

    empty = MockLLM()
    fresh = CachingLLM(path, empty)
    assert fresh.complete_structured("sys", "question a", Answer).text == "from a"
    assert fresh.complete_structured("sys", "question b", Answer).text == "from b"
    assert empty.calls == []