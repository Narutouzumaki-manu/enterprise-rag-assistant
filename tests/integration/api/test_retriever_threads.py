import threading
from datetime import datetime, timezone

import pytest

from app.retrieval.factory import build_default_retriever
from app.schemas.document import Chunk, ChunkMetadata, SourceType
from app.schemas.retrieval import RetrievalRequest


def _chunks(document_id: str, count: int) -> list[Chunk]:
    now = datetime.now(timezone.utc)
    return [
        Chunk(
            chunk_id=f"{document_id}_chunk_{n}",
            document_id=document_id,
            text=f"Quarter {n}: revenue grew by {n % 7} percent in region {n % 5}.",
            token_count=14,
            metadata=ChunkMetadata(
                document_id=document_id,
                source_type=SourceType.PDF,
                page_number=n + 1,
                section_title="Revenue",
                content_hash=f"hash-{document_id}",
                ingested_at=now,
            ),
        )
        for n in range(count)
    ]


@pytest.fixture(scope="module")
def retriever(tmp_path_factory):
    try:
        return build_default_retriever(persist_path=str(tmp_path_factory.mktemp("chroma")))
    except Exception as exc:  # for example the embedding model is not available offline
        pytest.skip(f"The retriever could not be built: {exc}")


def test_searching_while_documents_are_added_and_removed_does_not_fail(retriever):
    retriever.index_chunks(_chunks("base", 60))  # always present: searches must always find something
    errors: list[BaseException] = []
    stop = threading.Event()

    def searcher() -> None:
        try:
            while not stop.is_set():
                response = retriever.retrieve(
                    RetrievalRequest(query="revenue growth in the third quarter", top_k=5)
                )
                assert response.results
        except BaseException as exc:
            errors.append(exc)

    def writer() -> None:
        try:
            for i in range(6):
                document_id = f"doc{i}"
                retriever.index_chunks(_chunks(document_id, 20))
                if i % 2 == 1:
                    retriever.delete_document(document_id)  # doc1, doc3 and doc5 are removed again
        except BaseException as exc:
            errors.append(exc)

    searchers = [threading.Thread(target=searcher) for _ in range(3)]
    writer_thread = threading.Thread(target=writer)
    for thread in searchers:
        thread.start()
    writer_thread.start()
    writer_thread.join(timeout=180)
    stop.set()
    for thread in searchers:
        thread.join(timeout=60)

    assert not writer_thread.is_alive() and not any(t.is_alive() for t in searchers), "a thread hung"
    assert errors == []

    def found(document_id: str) -> int:
        request = RetrievalRequest(
            query="revenue growth", top_k=50, filters={"document_id": document_id}
        )
        return len(retriever.retrieve(request).results)

    assert found("doc1") == 0  # removed documents are really gone
    assert found("doc3") == 0
    assert found("doc0") == 20  # kept documents are complete
    assert found("doc2") == 20
    assert found("doc4") == 20