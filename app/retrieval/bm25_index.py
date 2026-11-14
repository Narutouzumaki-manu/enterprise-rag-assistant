import re

from rank_bm25 import BM25Okapi

from app.retrieval.filters import validate_filters
from app.schemas.document import Chunk
from app.schemas.retrieval import RetrievedChunk

_TOKEN_PATTERN = re.compile(r"\w+")


def tokenize(text: str) -> list[str]:
    """Lowercase the text and split it into words and numbers."""
    return _TOKEN_PATTERN.findall(text.lower())


def _matches(metadata: dict, filters: dict) -> bool:
    return all(metadata.get(key) == value for key, value in filters.items())


class BM25Index:
    """Exact-keyword search over chunks, kept in memory."""

    def __init__(self):
        # chunk_id -> {"text", "tokens", "token_set", "metadata"}
        self._entries: dict[str, dict] = {}
        self._bm25: BM25Okapi | None = None   # None means "needs rebuilding"
        self._ids: list[str] = []             # same order as the BM25 corpus

    def upsert(self, chunks: list[Chunk]) -> None:
        """Add chunks, or replace them if the chunk_id already exists."""
        if not chunks:
            return
        for chunk in chunks:
            tokens = tokenize(chunk.text)
            self._entries[chunk.chunk_id] = {
                "text": chunk.text,
                "tokens": tokens,
                "token_set": set(tokens),
                "metadata": {
                    "document_id": chunk.document_id,
                    "source_type": chunk.metadata.source_type.value,
                    "page_number": chunk.metadata.page_number,
                    "section_title": chunk.metadata.section_title,
                    "content_hash": chunk.metadata.content_hash,
                },
            }
        self._bm25 = None  # the old index is stale now

    def _ensure_index(self) -> None:
        """Rebuild the BM25 index if chunks were added or removed."""
        if self._bm25 is not None or not self._entries:
            return
        self._ids = list(self._entries.keys())
        corpus = [self._entries[chunk_id]["tokens"] for chunk_id in self._ids]
        if not any(corpus):
            return  # every chunk is empty, nothing to index
        self._bm25 = BM25Okapi(corpus)

    def search(
        self, query: str, k: int = 5, filters: dict | None = None
    ) -> list[RetrievedChunk]:
        """Return up to k chunks that share words with the query, best first."""
        filters = validate_filters(filters)
        query_tokens = tokenize(query or "")
        if not query_tokens or not self._entries:
            return []
        self._ensure_index()
        if self._bm25 is None:
            return []

        scores = self._bm25.get_scores(query_tokens)
        query_set = set(query_tokens)

        candidates = []
        for chunk_id, score in zip(self._ids, scores):
            entry = self._entries[chunk_id]
            if not (query_set & entry["token_set"]):
                continue  # shares no words with the query
            if filters and not _matches(entry["metadata"], filters):
                continue
            candidates.append((chunk_id, float(score)))

        candidates.sort(key=lambda pair: pair[1], reverse=True)

        results = []
        for chunk_id, score in candidates[:k]:
            entry = self._entries[chunk_id]
            results.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    document_id=entry["metadata"]["document_id"],
                    text=entry["text"],
                    sparse_score=score,
                    page_number=entry["metadata"]["page_number"],
                    section_title=entry["metadata"]["section_title"],
                )
            )
        return results

    def delete(self, document_id: str) -> int:
        """Remove every chunk of a document. Returns how many were removed."""
        to_remove = [
            chunk_id
            for chunk_id, entry in self._entries.items()
            if entry["metadata"]["document_id"] == document_id
        ]
        for chunk_id in to_remove:
            del self._entries[chunk_id]
        if to_remove:
            self._bm25 = None
        return len(to_remove)

    def restore(self, records: list[dict]) -> None:
        """Re-load chunks from stored records (used to rebuild after a restart).
        Each record looks like:
        {"chunk_id": ..., "text": ..., "metadata": {document_id, source_type,
         page_number, section_title, content_hash}}"""
        if not records:
            return
        for record in records:
            tokens = tokenize(record["text"])
            metadata = record["metadata"]
            self._entries[record["chunk_id"]] = {
                "text": record["text"],
                "tokens": tokens,
                "token_set": set(tokens),
                "metadata": {
                    "document_id": metadata["document_id"],
                    "source_type": metadata.get("source_type"),
                    "page_number": metadata.get("page_number"),
                    "section_title": metadata.get("section_title"),
                    "content_hash": metadata.get("content_hash"),
                },
            }
        self._bm25 = None  # the old index is stale now

    def clear(self) -> None:
        """Forget everything."""
        self._entries.clear()
        self._bm25 = None
        self._ids = []
    

    def count(self) -> int:
        return len(self._entries)