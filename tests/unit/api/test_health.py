
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import health


class WorkingFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def execute(self, statement):
        return None


class BrokenFactory(WorkingFactory):
    async def __aenter__(self):
        raise ConnectionError("unexpected connection_lost() call")


def make_client(monkeypatch, *, factory, redis="ok", retriever=object(), runtime=object()):
    app = FastAPI()
    app.include_router(health.router)
    app.state.db_session_factory = factory
    app.state.retriever = retriever
    app.state.runtime = runtime
    app.state.settings = SimpleNamespace(redis_url="redis://localhost:6379/0")

    async def fake_redis(request):
        return redis

    monkeypatch.setattr(health, "check_redis", fake_redis)
    return TestClient(app)


def test_everything_up(monkeypatch):
    response = make_client(monkeypatch, factory=WorkingFactory()).get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {
            "postgres": "ok",
            "redis": "ok",
            "retriever": "ok",
            "agent": "ok",
        },
    }


def test_postgres_down_is_503_and_degraded(monkeypatch):
    response = make_client(monkeypatch, factory=BrokenFactory()).get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["postgres"] == "unavailable"
    assert "connection" not in response.text.lower()


def test_no_database_is_503(monkeypatch):
    assert make_client(monkeypatch, factory=None).get("/health").status_code == 503


def test_redis_down_is_degraded_but_still_200(monkeypatch):
    response = make_client(
        monkeypatch, factory=WorkingFactory(), redis="unavailable"
    ).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["redis"] == "unavailable"


def test_disabled_parts_do_not_count_as_failures(monkeypatch):
    response = make_client(
        monkeypatch,
        factory=WorkingFactory(),
        retriever=None,
        runtime=None,
    ).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["checks"]["agent"] == "disabled"
