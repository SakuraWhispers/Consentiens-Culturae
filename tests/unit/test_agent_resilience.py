"""Resilience tests for the agent adapters (2026-10-20 live-run fixes).

Covers the two failures of run c2b65018…:

* the researcher wrote a param named "filter" (flat or nested) instead of
  "filter.type", which rejected the WHOLE plan — the shape is now normalized
  and a single bad call no longer takes the good calls down with it;
* the critic wrote severity "medium", which is not in the closed enum
  major|minor|info, and the WHOLE critique was thrown away — the value is now
  bridged, and a finding that still does not fit is dropped and REPORTED
  instead of taking the rest of the critique with it.

Offline via MockTransport.
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError as PydanticValidationError

from app.agents.analyst import draft_claims_llm, draft_plan_llm, review_claims_llm
from app.agents.researcher import PlanRejectedError, salvage_calls, validate_call


def _handler(content: str):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]},
        )

    return httpx.MockTransport(handler)


def _plan(content: str):
    with httpx.Client(transport=_handler(content)) as client:
        return draft_plan_llm(
            "k", "m", ["Mock Studio Notebooks"], "urn:tag:category:place:stationery_store",
            client=client,
        )


# --- researcher plan: transport-shape normalization -------------------------

def test_plan_insights_call_is_rejected_as_code_planned() -> None:
    """2026-10-24: the researcher's vocabulary is search-only. An insights
    call (even a historically-valid one) is rejected with the category
    instruction, because a model-written filter.tags URN would be an
    invented identifier."""
    content = json.dumps({"calls": [
        {"endpoint": "search", "params": {"query": "Mock Studio Notebooks"}},
        {"endpoint": "insights", "params": {
            "filter.type": "urn:entity:place",
            "filter.tags": "urn:tag:category:place:stationery_store"}},
    ]})
    plan = _plan(content)
    assert [c.endpoint for c in plan.calls] == ["search"]
    assert len(plan.rejected) == 1
    assert "planned by the code itself" in plan.rejected[0]


def test_plan_search_q_param_renamed_to_query() -> None:
    content = json.dumps({"calls": [{"endpoint": "search", "params": {"q": "ink pen"}}]})
    plan = _plan(content)
    assert plan.calls[0].params == {"query": "ink pen"}


def test_plan_normalization_cannot_smuggle_unknown_keys() -> None:
    # Normalization renames known shapes only; unknown keys are still rejected.
    content = json.dumps({"calls": [
        {"endpoint": "search", "params": {"query": "x", "evil_url": "https://x.test"}},
    ]})
    with pytest.raises(PlanRejectedError):
        _plan(content)


def test_plan_bad_call_dropped_good_calls_kept_and_reported() -> None:
    content = json.dumps({"calls": [
        {"endpoint": "search", "params": {"query": "good one"}},
        {"endpoint": "recs", "params": {}},
        {"endpoint": "search", "params": {"query": "good two"}},
    ]})
    plan = _plan(content)
    assert [c.params["query"] for c in plan.calls if c.endpoint == "search"] == [
        "good one",
        "good two",
    ]
    assert len(plan.rejected) == 1
    assert "allowlist" in plan.rejected[0]


def test_plan_with_nothing_usable_still_raises() -> None:
    content = json.dumps({"calls": [{"endpoint": "recs", "params": {}}]})
    with pytest.raises(PlanRejectedError):
        _plan(content)


def test_validate_call_rejects_insights_and_tags_as_code_planned() -> None:
    for endpoint in ("insights", "tags"):
        errors = validate_call(endpoint, {"filter.tags": "urn:tag:category:place:stationery_store"})
        assert any("planned by the code itself" in e for e in errors)


def test_salvage_calls_keeps_valid_and_reports_rejected() -> None:
    kept, rejected = salvage_calls([
        {"endpoint": "search", "params": {"query": "ok"}},
        {"endpoint": "search", "params": {"query": ""}},
    ])
    assert len(kept) == 1
    assert len(rejected) == 1
    assert "empty" in rejected[0]


# --- critic: synonym bridge + per-finding salvage --------------------------

_FINDING = {
    "issue_code": "UNSUPPORTED_CLAIM", "severity": "minor",
    "affected_concept_id": "A", "affected_claim_id": "claim-A",
    "evidence_ids": [], "explanation": "no evidence row backs the phrasing",
    "suggested_action": "qualify",
}


def _critic(content: str):
    with httpx.Client(transport=_handler(content)) as client:
        return review_claims_llm(
            "k", "m", [{"claim_id": "claim-A"}],
            {"A": {"rank": 1, "status": "RANKED", "weighted_total": 60.0}},
            [], client=client,
        )


def test_critic_severity_medium_bridged_to_minor() -> None:
    content = json.dumps({"findings": [{**_FINDING, "severity": "medium"}]})
    out = _critic(content)
    assert [f.severity for f in out.findings] == ["minor"]


def test_critic_lowercase_issue_code_normalized() -> None:
    content = json.dumps({"findings": [{**_FINDING, "issue_code": "unsupported_claim"}]})
    out = _critic(content)
    assert [f.issue_code for f in out.findings] == ["UNSUPPORTED_CLAIM"]


def test_critic_action_synonym_bridged() -> None:
    content = json.dumps({"findings": [{**_FINDING, "suggested_action": "reword"}]})
    out = _critic(content)
    assert [f.suggested_action for f in out.findings] == ["revise_wording"]


def test_critic_one_bad_finding_dropped_valid_ones_kept() -> None:
    content = json.dumps([
        {**_FINDING, "affected_claim_id": "claim-good"},
        {**_FINDING, "affected_claim_id": "claim-bad", "severity": "catastrophic"},
    ])
    out = _critic(content)
    assert [f.affected_claim_id for f in out.findings] == ["claim-good"]
    assert len(out.rejected) == 1
    assert "severity" in out.rejected[0]


def test_critic_all_findings_invalid_still_raises() -> None:
    content = json.dumps({"findings": [{**_FINDING, "severity": "catastrophic"}]})
    with pytest.raises(PydanticValidationError):
        _critic(content)


def test_critic_empty_findings_is_a_valid_no_issues_answer() -> None:
    out = _critic(json.dumps({"findings": []}))
    assert out.findings == []


# --- analyst: per-claim salvage --------------------------------------------

_BARE_CLAIM = {
    "claim_id": "claim-A", "concept_id": "A", "claim_type": "observation",
    "strength": "moderate", "confidence": "medium",
    "text": "Mock A ranks second on available evidence.",
    "evidence_ids": [], "score_fields": [], "audience_context": None,
}


def test_analyst_one_bad_claim_dropped_good_claim_kept() -> None:
    content = json.dumps([
        {**_BARE_CLAIM, "claim_id": "claim-good"},
        {**_BARE_CLAIM, "claim_id": "claim-bad", "strength": "rock-solid"},
    ])
    with httpx.Client(transport=_handler(content)) as client:
        draft = draft_claims_llm(
            "k", "m",
            {"A": {"rank": 1, "status": "RANKED", "weighted_total": 60.0}},
            {"A": {"available": 5, "total": 5}},
            [], {"c1": 1.0},
            client=client,
        )
    assert [c.claim_id for c in draft.claims] == ["claim-good"]
    assert len(draft.rejected) == 1
