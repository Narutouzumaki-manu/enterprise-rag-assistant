import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults():
    s = Settings(_env_file=None)
    assert s.agent_max_concurrent == 2
    assert s.sse_heartbeat_seconds == 15.0
    assert s.database_url.startswith("postgresql+asyncpg://")


def test_environment_overrides_default(monkeypatch):
    monkeypatch.setenv("AGENT_MAX_CONCURRENT", "5")
    assert Settings(_env_file=None).agent_max_concurrent == 5


def test_invalid_value_rejected(monkeypatch):
    monkeypatch.setenv("AGENT_MAX_CONCURRENT", "0")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_unrelated_environment_variables_are_ignored(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "not-a-real-key")
    Settings(_env_file=None)  # must not raise