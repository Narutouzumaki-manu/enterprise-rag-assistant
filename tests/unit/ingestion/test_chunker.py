from app.ingestion.chunker import _count_tokens, chunk_text


def test_chunk_text_returns_list_of_strings():
    text = "This is one sentence. This is another sentence."
    result = chunk_text(text, max_tokens=50, overlap_tokens=10)
    assert isinstance(result, list)
    assert all(isinstance(chunk, str) for chunk in result)


def test_chunk_text_empty_string_returns_empty_list():
    result = chunk_text("", max_tokens=50, overlap_tokens=10)
    assert result == []


def test_chunk_text_short_text_returns_single_chunk():
    """Text shorter than max_tokens should stay as one chunk, not be split."""
    text = "This is a short sentence."
    result = chunk_text(text, max_tokens=400, overlap_tokens=50)
    assert len(result) == 1
    assert result[0] == text


def test_chunk_text_respects_max_tokens():
    """No chunk should significantly exceed max_tokens."""
    long_text = "This is a test sentence about revenue growth. " * 50
    result = chunk_text(long_text, max_tokens=50, overlap_tokens=10)
    for chunk in result:
        assert _count_tokens(chunk) <= 60  # small buffer for sentence boundaries


def test_chunk_text_creates_multiple_chunks_for_long_text():
    long_text = "This is a test sentence about revenue growth. " * 50
    result = chunk_text(long_text, max_tokens=50, overlap_tokens=10)
    assert len(result) > 1


def test_chunk_text_has_overlap_between_consecutive_chunks():
    """The end of one chunk should share at least one sentence with the start of the next."""
    long_text = "Sentence A talks about revenue. Sentence B talks about costs. " * 30
    result = chunk_text(long_text, max_tokens=50, overlap_tokens=15)

    first_chunk_sentences = result[0].split(". ")
    second_chunk_sentences = result[1].split(". ")

    # last sentence of chunk 1 should appear somewhere in chunk 2
    assert any(first_chunk_sentences[-1] in s or s in first_chunk_sentences[-1]
               for s in second_chunk_sentences)


def test_chunk_text_never_splits_a_sentence_in_half():
    """Every chunk should end with sentence-ending punctuation, never mid-word."""
    long_text = "This is sentence one. This is sentence two. This is sentence three. " * 20
    result = chunk_text(long_text, max_tokens=30, overlap_tokens=5)
    for chunk in result:
        assert chunk.strip()[-1] in ".?!"