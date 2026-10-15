"""Decision brief input contract (SCOPE.md section 3, Input row).

Category is fixed to the demo category; users never choose it.
Weights cover the four soft criteria C1, C2, C3, C5 and must sum to 1
(architecture.md section 3.3). C4 is a gate with NO weight (human decision
2026-10-15): it never enters the weighted total, and a payload carrying a
\"c4\" weight is rejected rather than silently discarded.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Fixed demo category (SCOPE.md section 1). Never editable by the user.
DEMO_CATEGORY: str = "stationery and creative accessories"

MAX_CONSTRAINTS = 3
N_CONCEPTS = 3
N_CRITERIA = 5

CriterionId = Literal["C1", "C2", "C3", "C4", "C5"]

CRITERIA: tuple[str, ...] = ("C1", "C2", "C3", "C4", "C5")

WEIGHT_SUM_TOLERANCE = 1e-3


class Weights(BaseModel):
    """User weights over the four soft criteria. Each >= 0, sum = 1.

    extra="forbid" guarantees no hidden input: a submitted c4 key is rejected,
    not ignored. C4 (constraint feasibility) is checked as a pass/fail gate.
    """

    model_config = {"extra": "forbid"}

    c1: float = Field(ge=0.0, le=1.0, description="Cultural affinity alignment")
    c2: float = Field(ge=0.0, le=1.0, description="Differentiation")
    c3: float = Field(ge=0.0, le=1.0, description="Market-context relevance")
    c5: float = Field(ge=0.0, le=1.0, description="Evidence coverage")

    @model_validator(mode="after")
    def _sums_to_one(self) -> "Weights":
        total = self.c1 + self.c2 + self.c3 + self.c5
        if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
            raise ValueError(
                f"weights must sum to 1 (got {total:.6f})"
            )
        return self

    def as_dict(self) -> dict[str, float]:
        return {"C1": self.c1, "C2": self.c2, "C3": self.c3, "C5": self.c5}


class HardConstraint(BaseModel):
    """A user-listed hard constraint, checked as a gate (architecture.md section 3.2).

    v0.1 form: attribute/value equality against a concept's attribute map.
    Richer operators are deliberately deferred until real briefs exercise this.
    """

    attribute: str = Field(min_length=1, max_length=40, description='e.g. "price_band"')
    value: str = Field(min_length=1, max_length=100, description="allowed value, e.g. 'under 10'")
    note: str | None = Field(default=None, max_length=200)


class DecisionBrief(BaseModel):
    """The one input form. Exactly 3 concepts, up to 3 hard constraints."""

    category: Literal["stationery and creative accessories"] = DEMO_CATEGORY
    market: str = Field(min_length=1, max_length=120, description='e.g. "Lisbon, Portugal"')
    audience_description: str = Field(min_length=3, max_length=2000)
    business_goal: str = Field(min_length=3, max_length=2000)
    constraints: list[HardConstraint] = Field(default_factory=list, max_length=MAX_CONSTRAINTS)
    weights: Weights
    concepts: list["ConceptInput"] = Field(min_length=N_CONCEPTS, max_length=N_CONCEPTS)

    @field_validator("concepts")
    @classmethod
    def _unique_concept_ids(cls, v: list) -> list:
        ids = [c.concept_id for c in v]
        if len(set(ids)) != len(ids):
            raise ValueError("concept_id must be unique within a run")
        return v


from app.schemas.concept import ConceptInput  # noqa: E402  (forward-ref target)

DecisionBrief.model_rebuild()
