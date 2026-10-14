"""All agent caps and thresholds in one place (Backend Schema Section 5).

No node should contain its own magic numbers. Values marked INITIAL are
starting guesses, to be calibrated on Member 5's golden dataset.
"""
from dataclasses import dataclass

# Steps used by the first pass of a complex query:
# planner, retrieve, synthesize, fact-check.
FIRST_PASS_STEPS = 4
# Each retry repeats: retrieve, synthesize, fact-check.
STEPS_PER_RETRY = 3
# Largest top_k the backend accepts (ChatRequest limit).
TOP_K_LIMIT = 20


@dataclass(frozen=True)
class AgentConfig:
    top_k: int = 8                     # per search query; matches the backend default
    widened_top_k: int = 15            # used on retry 2; never above TOP_K_LIMIT
    max_subqueries: int = 5
    max_retries: int = 2
    max_steps: int = 12                # two retries on a complex query need 10 steps
    max_evidence_chunks: int = 20      # cap on merged evidence
    coverage_threshold: float = 0.8    # INITIAL value; calibrate on golden dataset
    max_confidence: float = 0.95       # never claim certainty (TRD Section 11)
    use_rewrites: bool = False         # also search the planner's rewrites (no measured benefit)
    use_similarity_hint: bool = False  # pass top-1 dense_score to the fact-checker
    llm_retries: int = 1               # retry a failed LLM call once, with backoff

    def __post_init__(self) -> None:
        if not 1 <= self.top_k <= TOP_K_LIMIT:
            raise ValueError(f"top_k must be between 1 and {TOP_K_LIMIT}")
        if not self.top_k <= self.widened_top_k <= TOP_K_LIMIT:
            raise ValueError(
                f"widened_top_k must be between top_k and {TOP_K_LIMIT}"
            )
        if self.max_subqueries < 1:
            raise ValueError("max_subqueries must be at least 1")
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if self.max_evidence_chunks < 1:
            raise ValueError("max_evidence_chunks must be at least 1")
        if not 0.0 <= self.coverage_threshold <= 1.0:
            raise ValueError("coverage_threshold must be between 0 and 1")
        if not 0.0 < self.max_confidence <= 1.0:
            raise ValueError("max_confidence must be above 0 and at most 1")
        if self.llm_retries < 0:
            raise ValueError("llm_retries cannot be negative")
        needed = FIRST_PASS_STEPS + STEPS_PER_RETRY * self.max_retries
        if self.max_steps < needed:
            raise ValueError(
                f"max_steps={self.max_steps} is too small for "
                f"max_retries={self.max_retries}: need at least {needed}"
            )