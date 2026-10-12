from collections import deque
from types import SimpleNamespace

import httpx
import pytest
from openai import (
    APITimeoutError,
    AuthenticationError,
    InternalServerError,
    RateLimitError,
)
from pydantic import BaseModel

from app.agents.llm import DEFAULT_MODEL, LLMClient, LLMError, OpenRouterLLM


class Answer(BaseModel):
    text: str
    score: float


class FakeClient:
    """Plays OpenRouter's part. Items: str (reply), Exception (raised), None (no choices)."""

    def __init__(self, outputs):
        self.outputs = deque(outputs)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        item = self.outputs.popleft()
        if isinstance(item, Exception):
            raise item
        if item is None:
            return SimpleNamespace(choices=[])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=item))]
        )


def _http_response(status):
    return httpx.Response(status, request=httpx.Request("POST", "https://example.test"))


def rate_limit():
    return RateLimitError("slow down", response=_http_response(429), body=None)


def server_error():
    return InternalServerError("oops", response=_http_response(500), body=None)


def auth_error():
    return AuthenticationError("bad key", response=_http_response(401), body=None)


def timeout():
    return APITimeoutError(request=httpx.Request("POST", "https://example.test"))


def make_llm(outputs, models=("model-a",), retries=1):
    client = FakeClient(outputs)
    sleeps = []
    llm = OpenRouterLLM(
        client, list(models), retries=retries, backoff_seconds=2.0, sleep=sleeps.append
    )
    return llm, client, sleeps


# ---- plain and structured answers -------------------------------------

def test_complete_returns_the_models_text():
    llm, _, _ = make_llm(["hello"])
    assert llm.complete("sys", "prompt") == "hello"


def test_complete_sends_system_and_user_messages_and_model():
    llm, client, _ = make_llm(["hello"])
    llm.complete("be brief", "what is 2+2?")
    request = client.requests[0]
    assert request["model"] == "model-a"
    assert request["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "what is 2+2?"},
    ]
    assert request["timeout"] == 60.0


def test_structured_parses_json_into_the_schema():
    llm, _, _ = make_llm(['{"text": "hi", "score": 0.5}'])
    result = llm.complete_structured("s", "p", Answer)
    assert result == Answer(text="hi", score=0.5)


def test_structured_strips_markdown_code_fences():
    llm, _, _ = make_llm(['```json\n{"text": "hi", "score": 0.5}\n```'])
    assert llm.complete_structured("s", "p", Answer).text == "hi"


def test_structured_request_asks_for_json_schema_and_repeats_it_in_system():
    llm, client, _ = make_llm(['{"text": "hi", "score": 0.5}'])
    llm.complete_structured("be strict", "p", Answer)
    request = client.requests[0]
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["name"] == "Answer"
    system = request["messages"][0]["content"]
    assert system.startswith("be strict")
    assert "JSON schema" in system
    assert "score" in system


# ---- bad output --------------------------------------------------------

def test_invalid_json_raises_llm_error_after_retrying():
    llm, client, _ = make_llm(["not json", "still not json"])
    with pytest.raises(LLMError):
        llm.complete_structured("s", "p", Answer)
    assert len(client.requests) == 2


def test_json_missing_a_field_raises_llm_error():
    llm, _, _ = make_llm(['{"text": "hi"}', '{"text": "hi"}'])
    with pytest.raises(LLMError, match="does not fit Answer"):
        llm.complete_structured("s", "p", Answer)


def test_empty_answer_raises_llm_error_after_retrying():
    llm, client, _ = make_llm(["", "   "])
    with pytest.raises(LLMError, match="empty answer"):
        llm.complete("s", "p")
    assert len(client.requests) == 2


def test_response_without_choices_raises_llm_error():
    llm, _, _ = make_llm([None, None])
    with pytest.raises(LLMError, match="no choices"):
        llm.complete("s", "p")


# ---- retries and backoff ----------------------------------------------

def test_transient_error_is_retried_then_succeeds():
    llm, client, sleeps = make_llm([rate_limit(), "ok"])
    assert llm.complete("s", "p") == "ok"
    assert len(client.requests) == 2
    assert sleeps == [2.0]


def test_backoff_doubles_each_attempt():
    llm, _, sleeps = make_llm([server_error(), timeout(), "ok"], retries=2)
    assert llm.complete("s", "p") == "ok"
    assert sleeps == [2.0, 4.0]


def test_retries_exhausted_raises_llm_error():
    llm, client, _ = make_llm([rate_limit(), rate_limit()], retries=1)
    with pytest.raises(LLMError):
        llm.complete("s", "p")
    assert len(client.requests) == 2


def test_non_retryable_error_is_not_retried():
    llm, client, sleeps = make_llm([auth_error()])
    with pytest.raises(LLMError):
        llm.complete("s", "p")
    assert len(client.requests) == 1
    assert sleeps == []


def test_zero_retries_makes_a_single_attempt():
    llm, client, _ = make_llm([rate_limit()], retries=0)
    with pytest.raises(LLMError):
        llm.complete("s", "p")
    assert len(client.requests) == 1


# ---- fallback models ---------------------------------------------------

def test_falls_back_to_next_model_after_a_failure():
    llm, client, _ = make_llm([auth_error(), "from b"], models=("a", "b"))
    assert llm.complete("s", "p") == "from b"
    assert [r["model"] for r in client.requests] == ["a", "b"]


def test_next_model_is_tried_only_after_retries_on_the_first():
    llm, client, _ = make_llm(
        [rate_limit(), rate_limit(), "from b"], models=("a", "b"), retries=1
    )
    assert llm.complete("s", "p") == "from b"
    assert [r["model"] for r in client.requests] == ["a", "a", "b"]


def test_all_models_failing_raises_llm_error():
    llm, _, _ = make_llm([auth_error(), auth_error()], models=("a", "b"))
    with pytest.raises(LLMError, match="All models failed"):
        llm.complete("s", "p")


# ---- setup -------------------------------------------------------------

def test_needs_at_least_one_model():
    with pytest.raises(ValueError, match="at least one model"):
        OpenRouterLLM(FakeClient([]), [])


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.setattr("app.agents.llm.load_dotenv", lambda: None)  # ignore real .env
    for name in ("OPENROUTER_API_KEY", "OPENROUTER_MODEL", "OPENROUTER_FALLBACK_MODELS"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_from_env_requires_an_api_key(clean_env):
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        OpenRouterLLM.from_env()


def test_from_env_reads_model_and_fallbacks(clean_env):
    clean_env.setenv("OPENROUTER_API_KEY", "test-key")
    clean_env.setenv("OPENROUTER_MODEL", "m1")
    clean_env.setenv("OPENROUTER_FALLBACK_MODELS", "m2, m3")
    assert OpenRouterLLM.from_env().models == ["m1", "m2", "m3"]


def test_from_env_defaults_to_nemotron_free(clean_env):
    clean_env.setenv("OPENROUTER_API_KEY", "test-key")
    assert OpenRouterLLM.from_env().models == [DEFAULT_MODEL]


def test_from_env_turns_off_the_sdks_own_retries(clean_env):
    clean_env.setenv("OPENROUTER_API_KEY", "test-key")
    assert OpenRouterLLM.from_env().client.max_retries == 0


def test_adapter_satisfies_the_protocol():
    llm, _, _ = make_llm([])
    assert isinstance(llm, LLMClient)