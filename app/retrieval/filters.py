ALLOWED_FILTER_KEYS = {
    "document_id",
    "source_type",
    "page_number",
    "section_title",
    "content_hash",
}


def validate_filters(filters: dict | None) -> dict | None:
    """Return the filters, or None if there is nothing to filter on.
    Raises ValueError for a key neither index knows about."""
    if not filters:
        return None
    unknown = set(filters) - ALLOWED_FILTER_KEYS
    if unknown:
        raise ValueError(
            f"Unknown filter key(s): {sorted(unknown)}. Allowed: {sorted(ALLOWED_FILTER_KEYS)}"
        )
    return filters


def to_chroma_where(filters: dict | None) -> dict | None:
    """Turn {"a": 1, "b": 2} into the format ChromaDB expects."""
    cleaned = validate_filters(filters)
    if cleaned is None:
        return None
    conditions = [{key: value} for key, value in cleaned.items()]
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}