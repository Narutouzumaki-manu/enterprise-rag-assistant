import logging
from uuid import UUID

from fastapi import Request

from app.db import repository

logger = logging.getLogger(__name__)

# Event types. Payloads carry ids and labels only: never passwords, tokens, API keys,
# question text, answer text or passage text.
LOGIN_FAILED = "login_failed"
UPLOAD = "upload"
DOCUMENT_DELETE = "document_delete"
QUERY = "query"
FEEDBACK = "feedback"


def _json_safe(payload: dict) -> dict:
    return {key: str(value) if isinstance(value, UUID) else value for key, value in payload.items()}


async def record_audit(request: Request, event_type: str, **payload) -> None:
    """Writes one audit row in its own short session. Never raises: a failed audit write is
    logged and the request carries on."""
    try:
        session_factory = request.app.state.db_session_factory
        if session_factory is None:
            return
        request_id = getattr(request.state, "request_id", None) or "unknown"
        async with session_factory() as db:
            await repository.record_audit_event(
                db, request_id=request_id, event_type=event_type, payload=_json_safe(payload)
            )
    except Exception as exc:
        logger.error("Could not record audit event %s (%s)", event_type, type(exc).__name__)