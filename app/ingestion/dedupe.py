from datetime import datetime, timezone


# In-memory registry: maps content_hash -> document info
# This is temporary scaffolding — will be replaced by a real
# Postgres lookup once Member 4's database schema is live.
_document_registry: dict[str, dict] = {}


def is_duplicate(content_hash: str) -> bool:
    """
    Checks whether a file with this content_hash has already been ingested.
    """
    return content_hash in _document_registry


def register_document(content_hash: str, document_id: str, filename: str) -> None:
    """
    Records a newly-ingested document's hash so future uploads
    of the same content can be detected as duplicates.
    """
    _document_registry[content_hash] = {
        "document_id": document_id,
        "filename": filename,
        "registered_at": datetime.now(timezone.utc),
    }


def get_registered_document(content_hash: str) -> dict | None:
    """
    Returns the registry entry for a given hash, or None if not found.
    Useful for returning a 'this was already uploaded as X' message.
    """
    return _document_registry.get(content_hash)


def clear_registry() -> None:
    """
    Wipes the in-memory registry. Mainly useful for tests, so each
    test starts with a clean slate instead of leaking state between them.
    """
    _document_registry.clear()


if __name__ == "__main__":
    # quick manual test
    test_hash = "abc123"
    print("Before registering:", is_duplicate(test_hash))

    register_document(test_hash, document_id="sample", filename="sample.csv")
    print("After registering:", is_duplicate(test_hash))

    print("Registered info:", get_registered_document(test_hash))

    clear_registry()
    print("After clearing:", is_duplicate(test_hash))