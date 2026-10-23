from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings

_hasher = PasswordHasher()


class TokenError(Exception):
    """The token is missing, malformed, expired or not signed by us. No detail on purpose."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)
DUMMY_PASSWORD_HASH = hash_password("not-a-real-password")  # used to even out login timing


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False  # wrong password or a broken hash: both are simply "no"


def create_access_token(user_id: UUID, settings: Settings, now: datetime | None = None) -> str:
    issued_at = now or datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> UUID:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],  # pinned: the token's own header is not trusted
            options={"require": ["sub", "exp", "iat"]},
        )
        return UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise TokenError("Invalid or expired token.") from None