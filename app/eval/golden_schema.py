from typing import Literal
from pydantic import BaseModel, Field, model_validator


CategoryType = Literal[
    "fact_lookup",
    "table",
    "numerical_comparison",
    "cross_section",
    "multi_fact",
    "comparison",
    "unanswerable",
]

StyleType = Literal["exact", "paraphrase"]


class GoldenQuestion(BaseModel):
    question_id: str
    question: str
    category: CategoryType
    style: StyleType
    evidence: list[str] = Field(default_factory=list)
    alt_evidence: list[str] = Field(default_factory=list)
    reference_answer: str = ""
    notes: str | None = None

    @model_validator(mode="after")
    def validate_rules(self) -> "GoldenQuestion":
        if self.category == "unanswerable":
            if self.evidence:
                raise ValueError(
                    f"Question '{self.question_id}' is unanswerable: evidence must be empty, got {self.evidence}"
                )
            if self.reference_answer.strip() != "":
                raise ValueError(
                    f"Question '{self.question_id}' is unanswerable: reference_answer must be empty, got {self.reference_answer!r}"
                )
        else:
            if not self.evidence or all(not str(e).strip() for e in self.evidence):
                raise ValueError(
                    f"Question '{self.question_id}' is answerable (category='{self.category}'): evidence must be non-empty"
                )
            if not self.reference_answer.strip():
                raise ValueError(
                    f"Question '{self.question_id}' is answerable (category='{self.category}'): reference_answer must be non-empty"
                )
        return self


class GoldenDataset(BaseModel):
    questions: list[GoldenQuestion]

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "GoldenDataset":
        seen: set[str] = set()
        duplicates: list[str] = []
        for q in self.questions:
            if q.question_id in seen:
                duplicates.append(q.question_id)
            seen.add(q.question_id)
        if duplicates:
            raise ValueError(f"Duplicate question_ids found: {duplicates}")
        return self


def validate_golden_questions(questions: list[dict | GoldenQuestion]) -> list[GoldenQuestion]:
    """Validate a list of questions, enforcing per-item schema rules and global id uniqueness."""
    parsed: list[GoldenQuestion] = []
    for item in questions:
        if isinstance(item, GoldenQuestion):
            parsed.append(item)
        else:
            parsed.append(GoldenQuestion.model_validate(item))
    dataset = GoldenDataset(questions=parsed)
    return dataset.questions

