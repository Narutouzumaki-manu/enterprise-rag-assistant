import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

import app.api.main as main_module
import app.api.routes.health as health_module
from app.api.dependencies import get_runtime
from app.api.main import create_app
from app.api.runtime import AgentRuntime
from app.core.config import Settings

from .mocks import MockAgent, MockRetriever


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)

async def _health_ok(request) -> str:
    return "ok"

def _probe_app(**kwargs):
    app = create_app(**kwargs)

    @app.get("/test/runtime")
    async def probe(runtime: AgentRuntime = Depends(get_runtime)):
        return {"ok": True}

    return app


def test_injected_agent_gets_a_runtime_with_settings_values():
    retriever = MockRetriever()
    settings = _settings(agent_max_concurrent=3, agent_wait_seconds=7.0)
    app = create_app(agent=MockAgent(), retriever=retriever, settings=settings)
    assert isinstance(app.state.runtime, AgentRuntime)
    assert app.state.retriever is retriever
    assert app.state.runtime._semaphore._value == 3
    assert app.state.runtime._wait_seconds == 7.0


@pytest.mark.asyncio
async def test_dependency_gives_the_runtime_when_an_agent_is_injected():
    transport = ASGITransport(app=_probe_app(agent=MockAgent()))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test/runtime")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_dependency_gives_503_when_no_agent_is_available():
    transport = ASGITransport(app=_probe_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test/runtime")
    assert response.status_code == 503
    assert response.json()["code"] == "DEPENDENCY_UNAVAILABLE"


def test_startup_builds_real_components_when_none_are_injected(monkeypatch):
    fake_retriever, fake_agent = MockRetriever(), MockAgent()
    monkeypatch.setattr(main_module, "build_real_components", lambda settings: (fake_retriever, fake_agent))
    monkeypatch.setattr(health_module, "check_postgres", _health_ok)
    monkeypatch.setattr(health_module, "check_redis", _health_ok)
    app = create_app(settings=_settings(agent_enabled=True))
    with TestClient(app) as client:
        assert isinstance(app.state.runtime, AgentRuntime)
        assert app.state.retriever is fake_retriever
        assert client.get("/health").status_code == 200


def test_startup_skips_the_build_when_the_agent_is_disabled(monkeypatch):
    def must_not_run(settings):
        raise AssertionError("build_real_components should not be called")

    monkeypatch.setattr(main_module, "build_real_components", must_not_run)
    monkeypatch.setattr(health_module, "check_postgres", _health_ok)
    monkeypatch.setattr(health_module, "check_redis", _health_ok)
    app = create_app(settings=_settings(agent_enabled=False))
    with TestClient(app) as client:
        assert app.state.runtime is None
        assert client.get("/health").status_code == 200


def test_startup_does_not_replace_an_injected_agent(monkeypatch):
    def must_not_run(settings):
        raise AssertionError("build_real_components should not be called")

    monkeypatch.setattr(main_module, "build_real_components", must_not_run)
    app = create_app(agent=MockAgent(), settings=_settings(agent_enabled=True))
    runtime_before = app.state.runtime
    with TestClient(app):
        assert app.state.runtime is runtime_before

def test_startup_creates_a_database_session_factory_when_none_is_injected():
    app = create_app(settings=_settings(agent_enabled=False))
    assert app.state.db_session_factory is None
    with TestClient(app):
        assert app.state.db_session_factory is not None


def test_startup_does_not_replace_an_injected_session_factory():
    sentinel = object()
    app = create_app(settings=_settings(agent_enabled=False), session_factory=sentinel)
    with TestClient(app):
        assert app.state.db_session_factory is sentinel