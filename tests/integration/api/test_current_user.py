from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import Depends
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_current_user
from app.api.main import create_app
from app.core.config import Settings
from app.core.security import create_access_token, hash_password
from app.db import models, repository

SETTINGS = Settings(_env_file=None, agent_enabled=False)
NOT_AUTHENTICATED = {"error": "Not authenticated.", "code": "UNAUTHENTICATED"}


def _app(session_factory=None):
    app = create_app(settings=SETTINGS, session_factory=session_factory)

    @app.get("/test/me")
    async def me(user: models.User = Depends(get_current_user)):
        return {"id": str(user.id), "email": user.email}

    return app


def _http(app) -> AsyncClient:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest_asyncio.fixture
async def user(session_factory):
    async with session_factory() as db:
        return await repository.create_user(db, "user@example.com", hash_password("pw-for-tests"))


@pytest.mark.asyncio
async def test_a_valid_token_gives_the_user(session_factory, user):
    token = create_access_token(user.id, SETTINGS)
    async with _http(_app(session_factory)) as http:
        r = await http.get("/test/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == {"id": str(user.id), "email": "user@example.com"}


@pytest.mark.asyncio
async def test_every_kind_of_bad_credentials_gets_the_same_401(session_factory, user):
    long_ago = datetime.now(timezone.utc) - timedelta(minutes=SETTINGS.jwt_expire_minutes + 5)
    cases = {
        "no header": {},
        "wrong scheme": {"Authorization": "Basic dXNlcjpwYXNz"},
        "garbage token": {"Authorization": "Bearer not-a-token"},
        "expired token": {
            "Authorization": f"Bearer {create_access_token(user.id, SETTINGS, now=long_ago)}"
        },
        "token for a user that does not exist": {
            "Authorization": f"Bearer {create_access_token(uuid4(), SETTINGS)}"
        },
    }
    async with _http(_app(session_factory)) as http:
        for name, headers in cases.items():
            r = await http.get("/test/me", headers=headers)
            assert r.status_code == 401, name
            assert r.json() == NOT_AUTHENTICATED, name
            assert r.headers["www-authenticate"] == "Bearer", name


@pytest.mark.asyncio
async def test_without_a_database_the_answer_is_503():
    async with _http(_app()) as http:
        r = await http.get("/test/me")
    assert r.status_code == 503
    assert r.json()["code"] == "DEPENDENCY_UNAVAILABLE"