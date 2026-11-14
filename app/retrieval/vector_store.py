import chromadb

from app.retrieval.embeddings import EmbeddingService
from app.retrieval.filters import to_chroma_where
from app.schemas.document import Chunk
from app.schemas.retrieval import RetrievedChunk

DEFAULT_COLLECTION = "chunks"


class VectorStore:
    """Saves chunk vectors in ChromaDB and finds the closest ones to a query."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        collection_name: str = DEFAULT_COLLECTION,
        persist_path: str | None = None,
    ):
        self.embedding_service = embedding_service
        # No path -> lives in memory only. With a path -> saved on disk.
        if persist_path:
            self.client = chromadb.PersistentClient(path=persist_path)
        else:
            self.client = chromadb.EphemeralClient()
        self.collection = self.client.get_or_create_collection(name=collection_name)
        self._check_model_consistency()

    def _check_model_consistency(self) -> None:
        """Never mix vectors from two different models in one collection."""
        if self.collection.count() == 0:
            return
        stored = self.collection.peek(limit=1)["metadatas"][0]
        if (
            stored.get("embedding_model") != self.embedding_service.model_name
            or stored.get("embedding_dimension") != self.embedding_service.dimension
        ):
            raise ValueError(
                "This collection was built with a different embedding model "
                f"({stored.get('embedding_model')}, {stored.get('embedding_dimension')} dims). "
                "Use a new collection or rebuild the index."
            )

    def _build_metadata(self, chunk: Chunk) -> dict:
        # ChromaDB does not accept None values, so we only include fields that exist
        metadata = {
            "document_id": chunk.document_id,
            "source_type": chunk.metadata.source_type.value,
            "content_hash": chunk.metadata.content_hash,
            "embedding_model": self.embedding_service.model_name,
            "embedding_dimension": self.embedding_service.dimension,
        }
        if chunk.metadata.page_number is not None:
            metadata["page_number"] = chunk.metadata.page_number
        if chunk.metadata.section_title is not None:
            metadata["section_title"] = chunk.metadata.section_title
        return metadata

    def upsert(self, chunks: list[Chunk]) -> None:
        """Insert chunks, or replace them if the chunk_id already exists."""
        if not chunks:
            return
        vectors = self.embedding_service.embed_documents(chunks)
        self.collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            embeddings=vectors,
            documents=[chunk.text for chunk in chunks],
            metadatas=[self._build_metadata(chunk) for chunk in chunks],
        )

    def search(
        self, query: str, k: int = 5, filters: dict | None = None
    ) -> list[RetrievedChunk]:
        """Return the k chunks closest in meaning to the query."""
        where = to_chroma_where(filters)
        if not query or not query.strip() or self.collection.count() == 0:
            return []
        query_vector = self.embedding_service.embed_query(query)
        result = self.collection.query(
            query_embeddings=[query_vector],
            n_results=min(k, self.collection.count()),
            where=where,
        )
        chunks = []
        for chunk_id, text, metadata, distance in zip(
            result["ids"][0],
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
        ):
            chunks.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    document_id=metadata["document_id"],
                    text=text,
                    # Chroma returns squared L2 distance. For length-1 vectors,
                    # similarity = 1 - distance / 2 (1.0 = identical meaning)
                    dense_score=1 - distance / 2,
                    page_number=metadata.get("page_number"),
                    section_title=metadata.get("section_title"),
                )
            )
        return chunks

    def delete(self, document_id: str) -> int:
        """Remove every chunk of a document. Returns how many were removed."""
        before = self.collection.count()
        self.collection.delete(where={"document_id": document_id})
        return before - self.collection.count()

    def export_records(self, batch_size: int = 500) -> list[dict]:
        """Read every stored chunk back out (text + metadata), in batches."""
        records = []
        offset = 0
        while True:
            batch = self.collection.get(
                limit=batch_size, offset=offset, include=["documents", "metadatas"]
            )
            ids = batch["ids"]
            if not ids:
                break
            for chunk_id, text, metadata in zip(ids, batch["documents"], batch["metadatas"]):
                records.append({"chunk_id": chunk_id, "text": text, "metadata": metadata})
            offset += len(ids)
        return records

    def count(self) -> int:
        return self.collection.count()