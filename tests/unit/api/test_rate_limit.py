import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from limits import parse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from app.api.limits import LOGIN_LIMIT, client_ip


def _make_app() -> FastAPI:
    # Own limiter, in-memory counters, enabled regardless of settings.
    limiter = Limiter(key_func=client_ip, storage_uri="memory://", enabled=True)
    app = FastAPI()
    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def _handler(request: Request, exc: RateLimitExceeded):
        # Stand-in for the real handler in app/api/errors.py
        return JSONResponse({"code": "RATE_LIMITED"}, status_code=429)

    @app.post("/login")
    @limiter.limit(LOGIN_LIMIT, key_func=client_ip)
    async def login(request: Request):
        return {"ok": True}

    return app


@pytest.mark.asyncio
async def test_login_is_limited_after_the_allowed_attempts():
    allowed = parse(LOGIN_LIMIT).amount
    transport = httpx.ASGITransport(app=_make_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(allowed):
            assert (await client.post("/login")).status_code == 200
        r = await client.post("/login")
    assert r.status_code == 429
    assert r.json()["code"] == "RATE_LIMITED"