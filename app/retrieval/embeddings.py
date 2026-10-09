from sentence_transformers import SentenceTransformer

from app.schemas.document import Chunk

DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"


class EmbeddingService:
    """Turns text into vectors (lists of numbers that capture meaning)."""

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME, query_prefix: str = ""):
        self.model_name = model_name
        self.query_prefix = query_prefix
        self.model = SentenceTransformer(model_name)
        # Measure the dimension from a real output, so we never hard-code it
        self.dimension = len(self.model.encode("dimension probe"))

    def embed_documents(self, chunks: list[Chunk], batch_size: int = 32) -> list[list[float]]:
        if not chunks:
            return []
        texts = [chunk.text for chunk in chunks]
        vectors = self.model.encode(
            texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return vectors.tolist()

    def embed_query(self, query: str) -> list[float]:
        if not query or not query.strip():
            return []
        vector = self.model.encode(
            query,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return vector.tolist()