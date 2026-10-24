"""Agent contract tests: schemas + researcher plan validation. Offline."""

from __future__ import annotations

import pytest

from app.agents.researcher import validate_plan
from app.agents.schemas import (
    AnalysisDraft,
    CriticOutput,
    RetrievalPlan,
    RichClaim,
)


def test_valid_plan_and_draft_pass() -> None:
    plan = RetrievalPlan(
        calls=[
            {"endpoint": "search", "params": {"query": "Mock notebook"}},
        ]
    )
    validate_plan(plan, max_calls=10)
    draft = AnalysisDraft(
        claims=[
            {
                "claim_id": "claim-A",
                "concept_id": "A",
                "claim_type": "observation",
                "strength": "moderate",
                "confidence": "medium",
                "text": "Mock A ranks first on available evidence.",
                "evidence_ids": ["abc123"],
                "score_fields": ["A.weighted_total"],
                "audience_context": None,
            }
        ]
    )
    assert draft.claims[0].confidence == "medium"


def test_off_allowlist_endpoint_rejected() -> None:
    # Schema is the first gate (Literal); the coordinator-level validator is
    # the second (plain tuples from researcher_fn). Both must reject.
    from pydantic import ValidationError as PydanticValidationError

    with pytest.raises(PydanticValidationError):
        RetrievalPlan(calls=[{"endpoint": "recs", "params": {}}])

    from app.workflow.coordinator import _validate_agent_plan

    kept, limits = _validate_agent_plan([(None, "recs", {})], ["A"], 10)
    assert kept == []
    assert any("allowlist" in lim for lim in limits)


def test_over_budget_plan_rejected() -> None:
    from pydantic import ValidationError as PydanticValidationError

    with pytest.raises(PydanticValidationError):
        RetrievalPlan(
            calls=[{"endpoint": "search", "params": {"query": f"q{i}"}} for i in range(11)]
        )

    from app.workflow.coordinator import _validate_agent_plan

    plan = [(None, "search", {"query": f"q{i}"}) for i in range(12)]
    kept, limits = _validate_agent_plan(plan, ["A"], 10)
    assert len(kept) == 10
    assert any("budget" in lim for lim in limits)


def test_unknown_param_key_rejected() -> None:
    plan = RetrievalPlan(calls=[{"endpoint": "search", "params": {"sql": "drop"}}])
    with pytest.raises(ValueError, match="param"):
        validate_plan(plan, max_calls=10)


def test_insights_call_is_no_longer_planner_legal() -> None:
    """2026-10-24 contract change: the researcher names a CATEGORY; the code
    resolves the tag and plans the insights call itself. Any insights (or
    tags) call in a plan is rejected - a model-written filter.tags URN would
    be an invented identifier (hard rule)."""
    from app.agents.researcher import PlanRejectedError

    plan = RetrievalPlan(calls=[
        {"endpoint": "search", "params": {"query": "q1"}},
        {"endpoint": "insights", "params": {
            "filter.type": "urn:entity:place",
            "filter.tags": "urn:tag:category:place:stationery_store"}},
    ])
    with pytest.raises(PlanRejectedError, match="planned by the code itself"):
        validate_plan(plan, max_calls=10)


def test_search_empty_query_rejected() -> None:
    from app.agents.researcher import PlanRejectedError

    plan = RetrievalPlan(calls=[{"endpoint": "search", "params": {"query": ""}}])
    with pytest.raises(PlanRejectedError, match="empty"):
        validate_plan(plan, max_calls=10)


def test_rich_claim_rejects_bad_confidence_and_long_context() -> None:
    with pytest.raises(ValueError):
        RichClaim(
            claim_id="c", concept_id="A", claim_type="observation", strength="weak",
            confidence="certain", text="t", evidence_ids=[], score_fields=[],
        )
    with pytest.raises(ValueError):
        RichClaim(
            claim_id="c", concept_id="A", claim_type="observation", strength="weak",
            confidence="low", text="t", evidence_ids=[], score_fields=[],
            audience_context="x" * 500,
        )


def test_critic_rejects_unknown_issue_code() -> None:
    with pytest.raises(ValueError):
        CriticOutput(
            findings=[
                {
                    "issue_code": "MADE_UP",
                    "severity": "minor",
                    "affected_concept_id": "A",
                    "affected_claim_id": "claim-A",
                    "evidence_ids": [],
                    "explanation": "x",
                    "suggested_action": "remove",
                }
            ]
        )
