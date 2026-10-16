"""Heuristic guard against instructions hidden in retrieved passages.

Passages are data, and the prompts say so, but a free model sometimes obeys an
instruction found inside a passage. This filter removes passages that address
the AI before the model or the fact-checker sees them.

It catches obvious attacks only: defence in depth, not a guarantee. It cannot
detect a plain false fact that contains no instruction.
"""
import re

from app.schemas.retrieval import RetrievedChunk

_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(?:ignore|disregard|forget)\s+(?:all\s+|any\s+|the\s+|your\s+)*"
        r"(?:previous|prior|above|earlier|preceding)\s+(?:instructions?|prompts?|rules|messages?)",
        r"(?:note|message|notice|instructions?)\s+to\s+the\s+(?:assistant|ai|model|llm|chatbot)",
        r"do\s+not\s+answer\s+the\s+user",
        r"mark\s+(?:every|all|each)\s+claims?\s+as\s+supported",
        r"(?:reveal|print|show|repeat)\s+(?:your\s+|the\s+)?system\s+prompt",
        r"\bthe\s+assistant\s+(?:must|should|will)\b",
    )
]


def looks_like_instructions(text: str) -> bool:
    flat = " ".join(text.split())
    return any(pattern.search(flat) for pattern in _PATTERNS)


def quarantine(
    chunks: list[RetrievedChunk],
) -> tuple[list[RetrievedChunk], list[RetrievedChunk]]:
    """Split chunks into (clean, removed), keeping the original order."""
    clean: list[RetrievedChunk] = []
    removed: list[RetrievedChunk] = []
    for chunk in chunks:
        (removed if looks_like_instructions(chunk.text) else clean).append(chunk)
    return clean, removed