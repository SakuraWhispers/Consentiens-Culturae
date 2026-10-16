"""Agent output contracts (G3). Thin prompt-and-schema wrappers, not services.

The coordinator validates every agent output; invalid output is retried once,
then replaced by the deterministic fallback with a recorded limitation.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Allowlisted Qloo endpoints the researcher may plan (docs/qloo-api-notes.md §3).
ALLOWLISTED_ENDPOINTS = ("search", "insights")

# Per-endpoint allowed query-param keys. Anything else is rejected before any
# network call (no model-chosen URLs, no model-generated code).
ALLOWED_PARAMS: dict[str, frozenset[str]] = {
    "search": frozenset({"query"}),
    "insights": frozenset({"filter.type", "filter.tags", "signal.interests.tags"}),
}

# Fixed critic issue codes (docs/architecture.md §5). Closed list.
ISSUE_CODES = (
    "UNSUPPORTED_CLAIM",
    "CLAIM_STRENGTH_EXCEEDS_EVIDENCE",
    "MISSING_EVIDENCE",
    "ENTITY_MATCH_AMBIGUOUS",
    "CONSTRAINT_VIOLATION",
    "SCORE_MISMATCH",
    "CAUSAL_OVERCLAIM",
    "CULTURAL_STEREOTYPE_RISK",
    "INCOMPARABLE_DATA",
    "CONTRADICTORY_RATIONALE",
)


class PlannedCall(BaseModel):
    endpoint: Literal["search", "insights"]
    params: dict[str, str] = Field(default_factory=dict)


class RetrievalPlan(BaseModel):
    calls: list[PlannedCall] = Field(min_length=1, max_length=10)


class RichClaim(BaseModel):
    """Analyst claim: base schema plus confidence and an optional NON-SCORED
    audience note (labeled context only — never enters weights or ranks)."""

    claim_id: str = Field(min_length=1, max_length=64)
    concept_id: str = Field(min_length=1, max_length=10)
    claim_type: Literal["observation", "interpretation", "recommendation"]
    strength: Literal["strong", "moderate", "weak"]
    confidence: Literal["high", "medium", "low"]
    text: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(default_factory=list)
    score_fields: list[str] = Field(default_factory=list)
    audience_context: str | None = Field(default=None, max_length=280)


class AnalysisDraft(BaseModel):
    claims: list[RichClaim] = Field(min_length=1)


class CriticFindingModel(BaseModel):
    issue_code: Literal[
        "UNSUPPORTED_CLAIM",
        "CLAIM_STRENGTH_EXCEEDS_EVIDENCE",
        "MISSING_EVIDENCE",
        "ENTITY_MATCH_AMBIGUOUS",
        "CONSTRAINT_VIOLATION",
        "SCORE_MISMATCH",
        "CAUSAL_OVERCLAIM",
        "CULTURAL_STEREOTYPE_RISK",
        "INCOMPARABLE_DATA",
        "CONTRADICTORY_RATIONALE",
    ]
    severity: Literal["major", "minor", "info"]
    affected_concept_id: str = Field(min_length=1, max_length=10)
    affected_claim_id: str = Field(min_length=1, max_length=64)
    evidence_ids: list[str] = Field(default_factory=list)
    explanation: str = Field(min_length=1, max_length=1000)
    suggested_action: Literal["remove", "qualify", "revise_wording"]


class CriticOutput(BaseModel):
    findings: list[CriticFindingModel] = Field(default_factory=list)


__all__ = [
    "ALLOWLISTED_ENDPOINTS",
    "ALLOWED_PARAMS",
    "ISSUE_CODES",
    "RetrievalPlan",
    "RichClaim",
    "AnalysisDraft",
    "CriticOutput",
]
