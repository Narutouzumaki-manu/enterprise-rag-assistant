from app.retrieval.metrics import mean, ndcg_at_k, recall_at_k, reciprocal_rank

relevant = {"finance_0", "finance_1"}

cases = {
    "A: right chunks at positions 2 and 4": ["x1", "finance_1", "x2", "finance_0", "x3"],
    "B: right chunks at positions 1 and 3": ["finance_0", "x1", "finance_1", "x2", "x3"],
    "C: perfect, positions 1 and 2": ["finance_0", "finance_1", "x1", "x2", "x3"],
    "D: nothing found": ["x1", "x2", "x3", "x4", "x5"],
}

print(f"{'case':<40}{'R@1':>7}{'R@3':>7}{'R@5':>7}{'RR':>7}{'NDCG@5':>9}")
reciprocal_ranks = []
for name, ranked in cases.items():
    rr = reciprocal_rank(ranked, relevant)
    reciprocal_ranks.append(rr)
    print(
        f"{name:<40}"
        f"{recall_at_k(ranked, relevant, 1):>7.3f}"
        f"{recall_at_k(ranked, relevant, 3):>7.3f}"
        f"{recall_at_k(ranked, relevant, 5):>7.3f}"
        f"{rr:>7.3f}"
        f"{ndcg_at_k(ranked, relevant, 5):>9.3f}"
    )

print("\nMean reciprocal rank over the four cases:", mean(reciprocal_ranks))