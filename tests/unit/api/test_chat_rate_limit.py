from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.limits import CHAT_LIMIT, limiter

from .mocks import MockAgent, make_chat_app


@pytest.mark.asyncio
async def test_requests_over_the_chat_limit_get_a_429_in_our_error_shape(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", True)  # restored after the test
    limiter.reset()  # a clean counter, whatever ran before

    allowed = int(CHAT_LIMIT.split("/")[0])
    app = make_chat_app(agent=MockAgent())
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        responses = [
            await client.post("/chat", json={"session_id": str(uuid4()), "query": "hi"})
            for _ in range(allowed + 1)
        ]
    codes = [r.status_code for r in responses]
    assert codes[:allowed] == [200] * allowed, f"codes={codes}"
    assert codes[allowed] == 429, f"codes={codes}"
    assert responses[allowed].json()["code"] == "RATE_LIMITED"
    assert "retry-after" in responses[allowed].headers