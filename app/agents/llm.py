"""LLM access for the agent (TRD Section 5.2).

Nodes depend on the LLMClient protocol, never on one provider, so tests
use MockLLM and the real run uses OpenRouterLLM.
"""
import json
import os
import re
import time
from collections.abc import Callable
from typing import Any, Protocol, TypeVar, runtime_checkable

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"


class LLMError(Exception):
    """Any failed LLM call: timeout, rate limit, or output that does not
    fit the requested schema. Nodes catch this one error type."""


@runtime_checkable
class LLMClient(Protocol):
    def complete(self, system: str, prompt: str) -> str:
        """Free-text answer."""
        ...

    def complete_structured(self, system: str, prompt: str, schema: type[T]) -> T:
        """Answer that must fit `schema`. Raises LLMError if it does not."""
        ...


class _BadOutput(Exception):
    """The model answered, but with nothing usable (empty, or wrong shape)."""


# Problems worth one more try: the same request may succeed a moment later.
_RETRYABLE = (
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
    _BadOutput,
)


def _strip_code_fences(text: str) -> str:
    """Models sometimes wrap JSON in a markdown fence; remove it."""
    text = text.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    return match.group(1) if match else text


class OpenRouterLLM:
    """LLMClient backed by OpenRouter's OpenAI-compatible API.

    models:  tried in order; a model gets its retries before the next is tried.
    retries: extra attempts per model for temporary problems (AgentConfig.llm_retries).
    """

    def __init__(
        self,
        client: Any,
        models: list[str],
        retries: int = 1,
        backoff_seconds: float = 2.0,
        timeout_seconds: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not models:
            raise ValueError("at least one model is required")
        self.client = client
        self.models = list(models)
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.timeout_seconds = timeout_seconds
        self.sleep = sleep

    @classmethod
    def from_env(cls, retries: int = 1) -> "OpenRouterLLM":
        load_dotenv()
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is not set (put it in .env)")
        primary = os.getenv("OPENROUTER_MODEL") or DEFAULT_MODEL
        fallbacks = [
            m.strip()
            for m in os.getenv("OPENROUTER_FALLBACK_MODELS", "").split(",")
            if m.strip()
        ]
        # max_retries=0: the SDK must not retry on its own, or one failure
        # would silently burn several of the daily free requests.
        client = OpenAI(base_url=BASE_URL, api_key=api_key, max_retries=0)
        return cls(client, [primary, *fallbacks], retries=retries)

    def complete(self, system: str, prompt: str) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        return self._call(messages)

    def complete_structured(self, system: str, prompt: str, schema: type[T]) -> T:
        schema_dict = schema.model_json_schema()
        full_system = (
            f"{system}\n\nRespond with ONLY a JSON object that matches this "
            f"JSON schema, with no other text:\n{json.dumps(schema_dict)}"
        )
        messages = [
            {"role": "system", "content": full_system},
            {"role": "user", "content": prompt},
        ]
        extra = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": schema_dict},
            }
        }

        def parse(text: str) -> T:
            try:
                return schema.model_validate_json(_strip_code_fences(text))
            except ValidationError as error:
                raise _BadOutput(
                    f"output does not fit {schema.__name__}: {error}"
                ) from error

        return self._call(messages, extra, parse)

    def _call(
        self,
        messages: list[dict],
        extra: dict | None = None,
        parse: Callable[[str], Any] = lambda text: text,
    ) -> Any:
        last_error: Exception | None = None
        for model in self.models:
            for attempt in range(self.retries + 1):
                try:
                    response = self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        timeout=self.timeout_seconds,
                        **(extra or {}),
                    )
                    choices = getattr(response, "choices", None)
                    if not choices:
                        raise _BadOutput("no choices in the response")
                    content = choices[0].message.content
                    if not content or not content.strip():
                        raise _BadOutput("empty answer")
                    return parse(content)
                except _RETRYABLE as error:
                    last_error = error
                    if attempt < self.retries:
                        self.sleep(self.backoff_seconds * 2**attempt)
                except APIError as error:
                    # e.g. wrong key, bad request: retrying the same model won't help
                    last_error = error
                    break
        raise LLMError(f"All models failed; last error: {last_error}")