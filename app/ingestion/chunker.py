import re

import tiktoken

_ENCODING = tiktoken.get_encoding("cl100k_base")


def _split_into_sentences(text: str) -> list[str]:
    """
    Naive sentence splitter: splits on '.', '?', '!' followed by whitespace.
    Not perfect (won't handle abbreviations like "Mr." correctly), but good
    enough as a starting point.
    """
    sentences = re.split(r'(?<=[.?!])\s+', text.strip())
    return [s for s in sentences if s]


def _count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def chunk_text(text: str, max_tokens: int = 400, overlap_tokens: int = 50) -> list[str]:
    """
    Splits text into token-aware chunks, respecting sentence boundaries.

    - max_tokens: target maximum tokens per chunk
    - overlap_tokens: approx how many tokens from the end of one chunk
      get repeated at the start of the next chunk, for context continuity
    """
    sentences = _split_into_sentences(text)
    if not sentences:
        return []

    chunks: list[str] = []
    current_sentences: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        sentence_tokens = _count_tokens(sentence)

        if current_tokens + sentence_tokens > max_tokens and current_sentences:
            chunks.append(" ".join(current_sentences))

            overlap_sentences = []
            overlap_count = 0
            for s in reversed(current_sentences):
                s_tokens = _count_tokens(s)
                if overlap_count + s_tokens > overlap_tokens:
                    break
                overlap_sentences.insert(0, s)
                overlap_count += s_tokens

            current_sentences = overlap_sentences
            current_tokens = overlap_count

        current_sentences.append(sentence)
        current_tokens += sentence_tokens

    if current_sentences:
        chunks.append(" ".join(current_sentences))

    return chunks


if __name__ == "__main__":
    sample_text = (
        "This is sentence one about revenue. This is sentence two about costs. "
        "This is sentence three about margins. This is sentence four about outlook. "
    ) * 20 # repeat to make it long enough to force multiple chunks

    result = chunk_text(sample_text, max_tokens=50, overlap_tokens=10)
    print(f"Total chunks created: {len(result)}")
    for i, chunk in enumerate(result):
        print(f"\n--- Chunk {i+1} ({_count_tokens(chunk)} tokens) ---")
        print(chunk)