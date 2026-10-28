from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.request_id import RequestIdMiddleware


def make_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ping")
    async def ping(request: Request):
        return {"id": request.state.request_id}

    return TestClient(app)


def test_an_id_is_generated_and_returned():
    response = make_client().get("/ping")
    assert response.headers["x-request-id"] == response.json()["id"]
    assert len(response.json()["id"]) == 32


def test_a_valid_incoming_id_is_kept():
    response = make_client().get("/ping", headers={"X-Request-ID": "abc-123.x"})
    assert response.headers["x-request-id"] == "abc-123.x"
    assert response.json()["id"] == "abc-123.x"


def test_an_unusable_incoming_id_is_replaced():
    for bad in ("has spaces in it", "a" * 65, "semi;colon"):
        response = make_client().get("/ping", headers={"X-Request-ID": bad})
        assert response.headers["x-request-id"] != bad
        assert len(response.headers["x-request-id"]) == 32


def test_each_request_gets_its_own_id():
    client = make_client()
    assert client.get("/ping").json()["id"] != client.get("/ping").json()["id"]