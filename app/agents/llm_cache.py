"""Replays saved LLM answers; calls the real model only on a miss.

Same key and file format as the throwaway cache that was in
scripts/measure_planner.py, so existing cache files keep working.
Failures are never cached. For development, evaluation and demos, not for a
production server.

Every write re-reads the file and merges, so two caches (or two scripts) using
the same file do not erase each other's entries. Two separate PROCESSES writing
at the same instant could still race; run one at a time.
"""
import hashlib
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.agents.llm import LLMClient, LLMError

T = TypeVar("T", bound=BaseModel)

# One lock shared by every CachingLLM in this process, so two instances writing
# the same file cannot overwrite each other's entries.
_FILE_LOCK = threading.Lock()


def _make_key(namespace: str, kind: str, system: str, prompt: str) -> str:
    parts = [kind, system, prompt]
    if namespace:
        parts.insert(0, namespace)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


class CachingLLM:
    """An LLMClient that remembers answers on disk.

    inner:       the real client, or a function that builds it (called only on
                 the first miss, so replaying needs no API key).
    namespace:   keeps answers from different models or prompt versions apart.
    replay_only: a miss raises LLMError instead of calling the model.
    """

    def __init__(
        self,
        path: str | Path,
        inner: LLMClient | Callable[[], LLMClient] | None,
        namespace: str = "",
        replay_only: bool = False,
    ) -> None:
        self.path = Path(path)
        self.namespace = namespace
        self.replay_only = replay_only
        self.hits = 0
        self.misses = 0  # real model calls attempted, including failed ones
        self._inner = inner if hasattr(inner, "complete_structured") else None
        self._factory = None if self._inner is not None else inner
        self._lock = threading.Lock()
        self._cache = self._read_file()

    @property
    def calls(self) -> int:
        """Real model calls made (the name the old script used)."""
        return self.misses

    def _read_file(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"LLM cache {self.path} is not valid JSON: {error}") from error
        if not isinstance(data, dict):
            raise ValueError(f"LLM cache {self.path} must contain a JSON object")
        return data

    def _store(self, key: str, value: object) -> None:
        with self._lock:
            self._cache[key] = value
        with _FILE_LOCK:
            # Merge with what is on disk now, so entries written by another
            # instance since we loaded the file are not lost.
            data = self._read_file()
            data[key] = value
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_name(self.path.name + ".tmp")
            temp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temp, self.path)

    def _before_real_call(self, kind: str) -> None:
        if self.replay_only:
            raise LLMError(f"No cached answer for this {kind} request (replay-only mode)")
        with self._lock:
            self.misses += 1

    def _client(self) -> LLMClient:
        with self._lock:
            if self._inner is None:
                if self._factory is None:
                    raise LLMError("No model is available to answer this request")
                self._inner = self._factory()
            return self._inner

    def complete(self, system: str, prompt: str) -> str:
        key = _make_key(self.namespace, "complete", system, prompt)
        with self._lock:
            cached = self._cache.get(key)
            if isinstance(cached, str):
                self.hits += 1
                return cached
        self._before_real_call("complete")
        text = self._client().complete(system, prompt)
        self._store(key, text)
        return text

    def complete_structured(self, system: str, prompt: str, schema: type[T]) -> T:
        key = _make_key(self.namespace, schema.__name__, system, prompt)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            try:
                result = schema.model_validate(cached)
            except ValidationError:
                result = None  # saved for an older version of the schema
            if result is not None:
                with self._lock:
                    self.hits += 1
                return result
        self._before_real_call(schema.__name__)
        result = self._client().complete_structured(system, prompt, schema)
        self._store(key, result.model_dump(mode="json"))
        return result