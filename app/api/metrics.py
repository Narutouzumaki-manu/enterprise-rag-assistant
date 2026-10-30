import time

from prometheus_client import Counter, Gauge, Histogram

REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"])
DURATION = Histogram(
    "http_request_duration_seconds",
    "Time until the request finished (a streamed answer counts until the stream ends)",
    ["method", "route"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)
AGENT_SLOTS_IN_USE = Gauge("agent_slots_in_use", "Agent runs currently holding a slot")

SKIPPED_PATHS = {"/metrics"}


def route_label(scope) -> str:
    """The route template, so ids never create new series. Unmatched paths share one label."""
    path = getattr(scope.get("route"), "path", None)
    return path or "unmatched"


class MetricsMiddleware:
    """Counts requests and times them. Plain ASGI on purpose (BaseHTTPMiddleware interferes
    with streaming responses)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in SKIPPED_PATHS:
            await self.app(scope, receive, send)
            return

        status = {"code": 500}  # what is counted if the app raises before it responds

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        started = time.monotonic()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = route_label(scope)
            REQUESTS.labels(scope["method"], route, str(status["code"])).inc()
            DURATION.labels(scope["method"], route).observe(time.monotonic() - started)