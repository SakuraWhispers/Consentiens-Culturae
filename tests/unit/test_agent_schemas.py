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
            {"endpoint": "insights", "params": {"filter.type": "urn:entity:place"}},
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


def test_insights_missing_filter_type_rejected() -> None:
    """Qloo /v2/insights REQUIRES filter.type (docs-verified §2; invalid params
    are silently IGNORED, so a plan without it ships unverifiable evidence).
    A researcher plan omitting it is rejected; the coordinator then falls back
    to the deterministic plan (which always carries filter.type) and records
    the rejection in limitations."""
    from app.agents.researcher import PlanRejectedError

    plan = RetrievalPlan(calls=[
        {"endpoint": "search", "params": {"query": "q1"}},
        {"endpoint": "insights", "params": {"filter.tags": "urn:tag:category:place:stationery_store"}},
    ])
    with pytest.raises(PlanRejectedError, match="filter.type"):
        validate_plan(plan, max_calls=10)


def test_insights_empty_filter_type_rejected() -> None:
    """Live-probe attempt 3 leak: the model sent filter.type='' which passed the
    key-presence check and sandbagged the insights call (200 + dead evidence).
    Empty-string values on allowlisted required params must be rejected too."""
    from app.agents.researcher import PlanRejectedError

    plan = RetrievalPlan(calls=[
        {"endpoint": "search", "params": {"query": "q1"}},
        {"endpoint": "insights", "params": {
            "filter.type": "", "filter.tags": "urn:tag:category:place:stationery_store"}},
    ])
    with pytest.raises(PlanRejectedError, match="filter.type"):
        validate_plan(plan, max_calls=10)


def test_insights_non_verified_filter_type_value_rejected() -> None:
    """Live-probe attempt 5: a semantically-wrong-but-non-empty filter.type
    ('urn:entity:category') passed the shape check and degraded the insights
    call the same way (63 rows + coverage error, vs 120 with the verified
    value). Only the docs-verified value is acceptable for this pipeline."""
    from app.agents.researcher import PlanRejectedError

    plan = RetrievalPlan(calls=[
        {"endpoint": "search", "params": {"query": "q1"}},
        {"endpoint": "insights", "params": {
            "filter.type": "urn:entity:category",
            "filter.tags": "urn:tag:category:place:stationery_store"}},
    ])
    with pytest.raises(PlanRejectedError, match="urn:entity:place"):
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
