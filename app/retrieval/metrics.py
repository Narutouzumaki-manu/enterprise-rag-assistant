import math


def recall_at_k(ranked_ids: list[str], relevant_ids, k: int) -> float:
    """Fraction of the right chunks that appear in the top k results."""
    relevant = set(relevant_ids)
    if not relevant or k <= 0:
        return 0.0
    found = relevant & set(ranked_ids[:k])
    return len(found) / len(relevant)


def reciprocal_rank(ranked_ids: list[str], relevant_ids) -> float:
    """1 / position of the first right chunk (position 1 is the top). 0 if none found."""
    relevant = set(relevant_ids)
    for position, chunk_id in enumerate(ranked_ids, start=1):
        if chunk_id in relevant:
            return 1.0 / position
    return 0.0


def ndcg_at_k(ranked_ids: list[str], relevant_ids, k: int) -> float:
    """How good the ordering of the top k is, from 0 to 1 (1 = right chunks come first)."""
    relevant = set(relevant_ids)
    if not relevant or k <= 0:
        return 0.0

    dcg = 0.0
    counted: set[str] = set()
    for position, chunk_id in enumerate(ranked_ids[:k], start=1):
        if chunk_id in relevant and chunk_id not in counted:
            counted.add(chunk_id)
            dcg += 1.0 / math.log2(position + 1)

    # The best possible score: every right chunk sitting at the very top
    best_possible_hits = min(len(relevant), k)
    ideal = sum(1.0 / math.log2(position + 1) for position in range(1, best_possible_hits + 1))
    return dcg / ideal


def mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0