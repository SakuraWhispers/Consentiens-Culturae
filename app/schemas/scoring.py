"""Scoring output contracts (architecture.md section 3). Code produces these; the LLM never does."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.brief import CriterionId

ScoreStatus = Literal["RANKED", "INFEASIBLE", "INSUFFICIENT_EVIDENCE"]

NormalizationMethod = Literal["min_max_across_concepts", "fixed_scale_0_100", "none"]

# Which criteria contribute to the weighted total. C4 is always gate-only
# (architecture.md section 3.2) - it never joins the weighted sum.
SOFT_CRITERIA: tuple[str, ...] = ("C1", "C2", "C3", "C5")


class CriterionScore(BaseModel):
    concept_id: str
    criterion: CriterionId
    raw: float | None = None
    value: float | None = Field(default=None, ge=0.0, le=100.0)
    method: NormalizationMethod = "none"
    weight_applied: float = 0.0
    weight_original: float = 0.0


class ConceptScore(BaseModel):
    """One concept's deterministic result. Ranks are computed only over RANKED concepts."""

    concept_id: str
    status: ScoreStatus = "RANKED"
    criterion_scores: list[CriterionScore] = Field(default_factory=list)
    weighted_total: float | None = None
    rank: int | None = Field(default=None, ge=1)
    coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    infeasible_reason: str | None = Field(default=None, max_length=300)
    insufficient_reason: str | None = Field(default=None, max_length=300)
    tie_broken_by: str | None = Field(default=None, max_length=300)
