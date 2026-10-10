from app.retrieval.bm25_index import BM25Index
from app.retrieval.embeddings import EmbeddingService
from app.retrieval.hybrid_search import HybridRetriever
from app.retrieval.reranker import Reranker
from app.retrieval.vector_store import VectorStore

# ---- Retrieval configuration v1 (revised) ----
# Chosen from the Session 11 measurements; see docs/MEMBER2_DECISIONS.md.
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
USE_KEYWORD_SEARCH = False            # True = merge meaning and keyword search (RRF)
RERANKER_MODEL: str | None = None     # e.g. "cross-encoder/ms-marco-MiniLM-L-6-v2" to switch it on
FETCH_K = 30
COLLECTION_NAME = "chunks"

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
KNOWN_QUERY_PREFIXES = {
    "BAAI/bge-small-en-v1.5": BGE_QUERY_PREFIX,
    "BAAI/bge-base-en-v1.5": BGE_QUERY_PREFIX,
}


def build_default_retriever(
    persist_path: str | None = None,
    *,
    collection_name: str = COLLECTION_NAME,
    embedding_model: str = EMBEDDING_MODEL,
    query_prefix: str | None = None,
    use_keyword: bool = USE_KEYWORD_SEARCH,
    reranker_model: str | None = RERANKER_MODEL,
    fetch_k: int = FETCH_K,
) -> HybridRetriever:
    """Build the retriever exactly as shipped. Build it ONCE per process (loading the model is slow)."""
    if query_prefix is None:
        query_prefix = KNOWN_QUERY_PREFIXES.get(embedding_model, "")
    embedding = EmbeddingService(embedding_model, query_prefix=query_prefix)
    store = VectorStore(embedding, collection_name=collection_name, persist_path=persist_path)
    reranker = Reranker(reranker_model) if reranker_model else None
    return HybridRetriever(store, BM25Index(), reranker, fetch_k=fetch_k, use_keyword=use_keyword)