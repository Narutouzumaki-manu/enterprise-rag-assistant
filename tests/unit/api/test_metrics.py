from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from app.api.metrics import MetricsMiddleware
from app.api.routes import prometheus


def make_client(runtime=None) -> TestClient:
    app = FastAPI()
    app.add_middleware(MetricsMiddleware)
    app.include_router(prometheus.router)
    app.state.runtime = runtime

    @app.get("/items/{item_id}")
    async def item(item_id: int):
        return {"id": item_id}

    @app.get("/boom")
    async def boom():
        raise ValueError("a bug")

    return TestClient(app, raise_server_exceptions=False)


def count(route: str, status: str, method: str = "GET") -> float:
    labels = {"method": method, "route": route, "status": status}
    return REGISTRY.get_sample_value("http_requests_total", labels) or 0.0


def test_requests_are_counted_by_route_template():
    client = make_client()
    before = count("/items/{item_id}", "200")
    client.get("/items/1")
    client.get("/items/2")
    assert count("/items/{item_id}", "200") - before == 2
    assert 'route="/items/1"' not in client.get("/metrics").text  # no series per id


def test_unmatched_paths_share_one_label():
    client = make_client()
    before = count("unmatched", "404")
    client.get("/nope-1")
    client.get("/nope-2")
    assert count("unmatched", "404") - before == 2


def test_an_unhandled_error_is_counted_as_500():
    client = make_client()
    before = count("/boom", "500")
    assert client.get("/boom").status_code == 500
    assert count("/boom", "500") - before == 1


def test_the_metrics_endpoint_does_not_count_itself():
    client = make_client()
    before = count("/metrics", "200")
    client.get("/metrics")
    assert count("/metrics", "200") == before


def test_agent_slots_gauge_is_read_at_scrape_time():
    client = make_client(runtime=SimpleNamespace(in_use=2))
    assert "agent_slots_in_use 2.0" in client.get("/metrics").text
    assert "agent_slots_in_use 0.0" in make_client(runtime=None).get("/metrics").text