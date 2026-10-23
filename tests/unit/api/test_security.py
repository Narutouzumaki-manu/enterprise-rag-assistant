from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import DEV_JWT_SECRET, Settings
from app.core.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

SETTINGS = Settings(_env_file=None)


# ---------- passwords ----------

def test_a_password_is_stored_as_a_salted_argon2_hash():
    first, second = hash_password("correct horse"), hash_password("correct horse")
    assert first.startswith("$argon2")
    assert "correct horse" not in first
    assert first != second  # each hash has its own salt
    assert verify_password("correct horse", first)


def test_a_wrong_password_is_rejected():
    assert verify_password("wrong", hash_password("correct horse")) is False


def test_a_broken_hash_is_rejected_without_raising():
    assert verify_password("anything", "not-a-hash") is False
    assert verify_password("anything", "") is False


# ---------- tokens ----------

def test_a_token_round_trips_to_the_same_user_id():
    user_id = uuid4()
    assert decode_access_token(create_access_token(user_id, SETTINGS), SETTINGS) == user_id


def test_an_expired_token_is_rejected():
    long_ago = datetime.now(timezone.utc) - timedelta(minutes=SETTINGS.jwt_expire_minutes + 5)
    token = create_access_token(uuid4(), SETTINGS, now=long_ago)
    with pytest.raises(TokenError):
        decode_access_token(token, SETTINGS)


def test_a_tampered_token_is_rejected():
    token = create_access_token(uuid4(), SETTINGS)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(TokenError):
        decode_access_token(tampered, SETTINGS)


def test_a_token_signed_with_another_secret_is_rejected():
    other = Settings(_env_file=None, jwt_secret="a-completely-different-secret-of-40-chars!")
    token = create_access_token(uuid4(), other)
    with pytest.raises(TokenError):
        decode_access_token(token, SETTINGS)


def test_an_unsigned_none_algorithm_token_is_rejected():
    now = datetime.now(timezone.utc)
    payload = {"sub": str(uuid4()), "iat": now, "exp": now + timedelta(minutes=5)}
    forged = jwt.encode(payload, key=None, algorithm="none")
    with pytest.raises(TokenError):
        decode_access_token(forged, SETTINGS)


def test_a_token_missing_required_claims_is_rejected():
    no_exp = jwt.encode({"sub": str(uuid4())}, SETTINGS.jwt_secret, algorithm=SETTINGS.jwt_algorithm)
    with pytest.raises(TokenError):
        decode_access_token(no_exp, SETTINGS)


def test_a_subject_that_is_not_a_uuid_is_rejected():
    now = datetime.now(timezone.utc)
    payload = {"sub": "not-a-uuid", "iat": now, "exp": now + timedelta(minutes=5)}
    token = jwt.encode(payload, SETTINGS.jwt_secret, algorithm=SETTINGS.jwt_algorithm)
    with pytest.raises(TokenError):
        decode_access_token(token, SETTINGS)


# ---------- the production guard ----------

def test_production_refuses_the_dev_secret():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production")


def test_production_refuses_a_short_secret():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production", jwt_secret="short")


def test_production_accepts_a_long_random_secret():
    settings = Settings(_env_file=None, environment="production", jwt_secret="x" * 40)
    assert settings.jwt_secret == "x" * 40


def test_a_blank_secret_in_the_environment_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "")
    assert Settings(_env_file=None).jwt_secret == DEV_JWT_SECRET