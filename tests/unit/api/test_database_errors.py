import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.errors import register_error_handlers


def make_client(exc: Exception) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    async def boom():
        raise exc

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    "exc",
    [
        OperationalError("SELECT 1", {}, Exception("server closed the connection")),
        ConnectionError("unexpected connection_lost() call"),
        ConnectionRefusedError(),
        TimeoutError(),
    ],
)
def test_database_failures_become_503(exc):
    response = make_client(exc).get("/boom")
    assert response.status_code == 503
    assert response.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "Retry-After" in response.headers
    assert "connection" not in response.json()["error"].lower()  # no internal detail


def test_other_errors_stay_500():
    response = make_client(ValueError("a bug")).get("/boom")
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"