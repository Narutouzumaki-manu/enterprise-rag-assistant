from fastapi import Request
from slowapi import Limiter

from app.core.config import get_settings

_settings = get_settings()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def user_or_ip(request: Request) -> str:
    """Per user once get_current_user has run, per address otherwise."""
    user_id = getattr(request.state, "user_id", None)
    return f"user:{user_id}" if user_id else f"ip:{client_ip(request)}"


# Redis down: swallow_errors skips the limit check instead of failing the request (degrade).
limiter = Limiter(
    key_func=user_or_ip,
    storage_uri=_settings.rate_limit_storage_url or _settings.redis_url,
    enabled=_settings.rate_limit_enabled,
    in_memory_fallback_enabled=True,   # count in memory while Redis is unreachable
)

LOGIN_LIMIT = _settings.login_rate_limit
CHAT_LIMIT = _settings.chat_rate_limit
UPLOAD_LIMIT = _settings.upload_rate_limit