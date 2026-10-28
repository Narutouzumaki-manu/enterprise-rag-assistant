import logging
import re
import time
import uuid

import structlog

logger = logging.getLogger("app.request")
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")  # fits audit_events.request_id (64)


class RequestIdMiddleware:
    """Gives every request an id: logged on every line, stored on request.state and returned in
    the X-Request-ID header. Plain ASGI on purpose (BaseHTTPMiddleware interferes with
    streaming responses)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(b"x-request-id")
        request_id = None
        if incoming:
            candidate = incoming.decode("latin-1")
            if _VALID_ID.match(candidate):  # anything else (too long, odd characters) is replaced
                request_id = candidate
        request_id = request_id or uuid.uuid4().hex

        scope.setdefault("state", {})["request_id"] = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        status = {"code": 0}

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                message["headers"] = [*message.get("headers", []), (b"x-request-id", request_id.encode())]
            await send(message)

        started = time.monotonic()
        try:
            await self.app(scope, receive, send_with_id)
        finally:
            logger.info(
                "%s %s -> %s in %.0f ms",
                scope["method"],
                scope["path"],  # the path only: never the query string
                status["code"],
                (time.monotonic() - started) * 1000,
            )
            structlog.contextvars.clear_contextvars()