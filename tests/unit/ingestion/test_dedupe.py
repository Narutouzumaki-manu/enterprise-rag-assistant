import pytest
from app.ingestion.dedupe import (
    is_duplicate,
    register_document,
    get_registered_document,
    clear_registry,
)


@pytest.fixture(autouse=True)
def reset_registry():
    """Runs before AND after every test, so tests never leak state into each other."""
    clear_registry()
    yield
    clear_registry()


def test_is_duplicate_false_for_unseen_hash():
    assert is_duplicate("some_hash_never_seen") is False


def test_is_duplicate_true_after_registering():
    register_document("hash123", document_id="doc1", filename="report.pdf")
    assert is_duplicate("hash123") is True


def test_get_registered_document_returns_correct_info():
    register_document("hash456", document_id="doc2", filename="invoice.csv")
    info = get_registered_document("hash456")

    assert info is not None
    assert info["document_id"] == "doc2"
    assert info["filename"] == "invoice.csv"


def test_get_registered_document_returns_none_for_unknown_hash():
    result = get_registered_document("nonexistent_hash")
    assert result is None


def test_clear_registry_removes_all_entries():
    register_document("hash789", document_id="doc3", filename="notes.docx")
    assert is_duplicate("hash789") is True

    clear_registry()

    assert is_duplicate("hash789") is False


def test_registering_same_hash_twice_overwrites_not_duplicates():
    """Re-registering the same hash should update the entry, not error out."""
    register_document("hashABC", document_id="doc4", filename="v1.pdf")
    register_document("hashABC", document_id="doc4", filename="v1_renamed.pdf")

    info = get_registered_document("hashABC")
    assert info["filename"] == "v1_renamed.pdf"