import pytest
from sqlalchemy import select

from app.db import models, repository


@pytest.mark.asyncio
async def test_an_audit_event_is_stored_with_its_payload(session_factory):
    async with session_factory() as db:
        await repository.record_audit_event(
            db, request_id="req-1", event_type="login_failed", payload={"client": "127.0.0.1"}
        )
    async with session_factory() as db:
        rows = (await db.execute(select(models.AuditEvent))).scalars().all()
    assert len(rows) == 1
    assert rows[0].request_id == "req-1"
    assert rows[0].event_type == "login_failed"
    assert rows[0].payload == {"client": "127.0.0.1"}