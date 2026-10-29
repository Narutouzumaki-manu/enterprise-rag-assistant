from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api import audit


class BrokenFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        raise ConnectionError("unexpected connection_lost() call")

    async def __aexit__(self, *exc_info):
        return False


def fake_request(factory):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(db_session_factory=factory)),
        state=SimpleNamespace(request_id="req-1"),
    )


@pytest.mark.asyncio
async def test_a_failed_audit_write_never_raises(caplog):
    await audit.record_audit(fake_request(BrokenFactory()), audit.UPLOAD, document_id="d1")
    assert "Could not record audit event upload" in caplog.text
    assert "ConnectionError" in caplog.text


@pytest.mark.asyncio
async def test_no_database_means_nothing_is_written():
    await audit.record_audit(fake_request(None), audit.UPLOAD, document_id="d1")  # must not raise


def test_uuids_are_made_json_safe():
    value = uuid4()
    assert audit._json_safe({"session_id": value, "streamed": True}) == {
        "session_id": str(value),
        "streamed": True,
    }