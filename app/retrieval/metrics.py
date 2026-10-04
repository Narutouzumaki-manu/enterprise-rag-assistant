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
def merge_identical_needs(needs) -> list[set]:
    """Two facts that live in exactly the same chunks are one need for the search."""
    unique: list[set] = []
    for need in needs:
        need = set(need)
        if need not in unique:
            unique.append(need)
    return unique


def needs_ranking(ranked_ids: list[str], needs) -> list[str]:
    """Replace the first chunk that satisfies each need with a label (need:0, need:1 ...).
    Other chunks, and repeat chunks for a need that is already satisfied, stay as they are."""
    needs = [set(need) for need in needs]

    seen: set[str] = set()
    for need in needs:
        if seen & need:
            raise ValueError("Two different facts share a chunk, so scoring by facts is ambiguous.")
        seen |= need

    chunk_to_need = {chunk_id: i for i, need in enumerate(needs) for chunk_id in need}
    satisfied: set[int] = set()
    result = []
    for chunk_id in ranked_ids:
        need_index = chunk_to_need.get(chunk_id)
        if need_index is not None and need_index not in satisfied:
            satisfied.add(need_index)
            result.append(f"need:{need_index}")
        else:
            result.append(chunk_id)
    return result


def score_against_needs(
    ranked_ids: list[str], needs, recall_ks=(5, 10), ndcg_k: int = 10
) -> dict[str, float]:
    """Score one question's ranking by the facts it found (not by how many chunks)."""
    needs = merge_identical_needs(needs)
    if not needs or any(not need for need in needs):
        raise ValueError("This question has no scorable facts (is it an unanswerable one?).")

    mapped = needs_ranking(ranked_ids, needs)
    relevant = {f"need:{i}" for i in range(len(needs))}

    scores = {f"recall@{k}": recall_at_k(mapped, relevant, k) for k in recall_ks}
    scores["mrr"] = reciprocal_rank(mapped, relevant)
    scores[f"ndcg@{ndcg_k}"] = ndcg_at_k(mapped, relevant, ndcg_k)
    return scores