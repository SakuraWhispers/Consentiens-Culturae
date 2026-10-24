"""Agent output contracts (G3). Thin prompt-and-schema wrappers, not services.

The coordinator validates every agent output; invalid output is retried once,
then replaced by the deterministic fallback with a recorded limitation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

# Allowlisted Qloo endpoints the researcher may plan (docs/qloo-api-notes.md §3).
# Planner allowlist (2026-10-24): the researcher proposes SEARCH calls and
# names a CATEGORY; code resolves the tag ("/v2/tags", docs-verified) and
# makes the shared insights call itself. A model-written filter.tags URN
# would be an invented identifier, so "insights" is no longer planner-legal.
ALLOWLISTED_ENDPOINTS = ("search",)
ALLOWLISTED_ENDPOINTS_PLUMBING = ("search", "tags", "insights")

# Per-endpoint allowed query-param keys. Anything else is rejected before any
# network call (no model-chosen URLs, no model-generated code).
ALLOWED_PARAMS: dict[str, frozenset[str]] = {
    "search": frozenset({"query"}),
    "tags": frozenset({"filter.query"}),
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
    endpoint: Literal["search", "tags", "insights"]
    params: dict[str, str] = Field(default_factory=dict)


class RetrievalPlan(BaseModel):
    calls: list[PlannedCall] = Field(min_length=1, max_length=10)
    # The researcher CHOOSES the category (2026-10-24): code resolves it to a
    # place-category tag via /v2/tags; the model never writes a URN itself.
    category: str | None = Field(default=None, max_length=120)
    # Resilience (2026-10-20): calls that did not pass the rules are reported,
    # not swallowed; raw_head keeps a truncated copy of the model payload for
    # diagnosis (it never contains keys or Qloo payloads).
    rejected: list[str] = Field(default_factory=list)
    raw_head: str = ""


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
    rejected: list[str] = Field(default_factory=list)
    raw_head: str = ""


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
    rejected: list[str] = Field(default_factory=list)
    raw_head: str = ""


@dataclass
class AgentOutput:
    """Hook result carrier for the coordinator.

    `items` are the entries code accepted; `rejected` names every entry that
    was dropped (one line each, safe to show in a report limitation); and
    `raw_head` is a truncated copy of the model payload, persisted as a
    workflow event so a live failure can be diagnosed from the database
    instead of guessed at.
    """

    items: list[Any] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    raw_head: str = ""
    # The researcher's chosen category travels beside the calls (2026-10-24).
    category: str | None = None


__all__ = [
    "ALLOWLISTED_ENDPOINTS",
    "ALLOWED_PARAMS",
    "ISSUE_CODES",
    "RetrievalPlan",
    "RichClaim",
    "AnalysisDraft",
    "CriticOutput",
    "AgentOutput",
]
