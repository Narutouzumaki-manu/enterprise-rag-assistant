from app.retrieval.metrics import score_against_needs

cases = {
    "1: like q07, one fact, three acceptable chunks, found second": (
        ["x", "a2", "x2"], [{"a1", "a2", "a3"}]),
    "2: like q02, two facts in the very same chunk, found third": (
        ["x", "y", "c60"], [{"c60"}, {"c60"}]),
    "3: like q15, two facts, found at positions 1 and 7": (
        ["m2", "x", "y", "z", "w", "v", "m1"], [{"m1"}, {"m2"}]),
    "4: nothing found": (["x", "y", "z"], [{"a"}]),
}

print(f"{'case':<64}{'R@5':>7}{'R@10':>7}{'MRR':>7}{'NDCG@10':>9}")
for name, (ranked, needs) in cases.items():
    s = score_against_needs(ranked, needs)
    print(f"{name:<64}{s['recall@5']:>7.3f}{s['recall@10']:>7.3f}{s['mrr']:>7.3f}{s['ndcg@10']:>9.3f}")