import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from app.api.main import create_app
from app.core.config import Settings
from app.core.security import decode_access_token, hash_password
from app.db import repository

SETTINGS = Settings(_env_file=None, agent_enabled=False)
PASSWORD = "correct horse battery"


def _http(app) -> AsyncClient:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest_asyncio.fixture
async def client(session_factory):
    app = create_app(settings=SETTINGS, session_factory=session_factory)
    async with _http(app) as http:
        yield http


async def _make_user(session_factory, email="user@example.com"):
    async with session_factory() as db:
        return await repository.create_user(db, email, hash_password(PASSWORD))


@pytest.mark.asyncio
async def test_login_returns_a_token_for_the_right_user(client, session_factory):
    user = await _make_user(session_factory)
    r = await client.post("/auth/login", json={"email": "user@example.com", "password": PASSWORD})
    assert r.status_code == 200
    data = r.json()
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == SETTINGS.jwt_expire_minutes * 60
    assert decode_access_token(data["access_token"], SETTINGS) == user.id


@pytest.mark.asyncio
async def test_wrong_password_gives_401(client, session_factory):
    await _make_user(session_factory)
    r = await client.post("/auth/login", json={"email": "user@example.com", "password": "wrong-password"})
    assert r.status_code == 401
    assert r.json() == {"error": "Incorrect email or password.", "code": "UNAUTHENTICATED"}
    assert r.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_unknown_email_looks_exactly_like_a_wrong_password(client, session_factory):
    await _make_user(session_factory)
    wrong_password = await client.post(
        "/auth/login", json={"email": "user@example.com", "password": "wrong-password"}
    )
    unknown_email = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    assert unknown_email.status_code == wrong_password.status_code == 401
    assert unknown_email.json() == wrong_password.json()


@pytest.mark.asyncio
async def test_email_is_case_insensitive_and_trimmed(client, session_factory):
    await _make_user(session_factory, "user@example.com")
    r = await client.post("/auth/login", json={"email": "  USER@Example.COM ", "password": PASSWORD})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_missing_password_is_a_validation_error(client):
    r = await client.post("/auth/login", json={"email": "user@example.com"})
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_the_same_email_cannot_be_created_twice(session_factory):
    await _make_user(session_factory, "a@example.com")
    with pytest.raises(IntegrityError):
        await _make_user(session_factory, "A@EXAMPLE.COM")  # same account after normalising
    async with session_factory() as db:
        assert await repository.get_user_by_email(db, "a@example.com") is not None


@pytest.mark.asyncio
async def test_an_unknown_email_gives_no_user(session_factory):
    async with session_factory() as db:
        assert await repository.get_user_by_email(db, "nobody@example.com") is None


@pytest.mark.asyncio
async def test_login_without_a_database_gives_503():
    async with _http(create_app(settings=SETTINGS)) as http:
        r = await http.post("/auth/login", json={"email": "user@example.com", "password": PASSWORD})
    assert r.status_code == 503
    assert r.json()["code"] == "DEPENDENCY_UNAVAILABLE"