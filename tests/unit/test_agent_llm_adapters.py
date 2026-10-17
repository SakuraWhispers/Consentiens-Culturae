"""Agent LLM adapter normalization (G3). Offline via MockTransport.

Covers the live-probe failure: models return list-shaped tag params; code
normalizes to comma-joined strings BEFORE schema validation (transport-shape
normalization, not model discretion — allowlist keys are still enforced).
"""

from __future__ import annotations

import json

import httpx

from app.agents.analyst import draft_plan_llm


def _handler(content: str):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]},
        )

    return httpx.MockTransport(handler)


def test_plan_params_list_normalized_to_string() -> None:
    content = json.dumps({
        "calls": [
            {"endpoint": "search", "params": {"query": "Mock Studio Notebooks"}},
            {"endpoint": "insights", "params": {
                "filter.type": "urn:entity:place",
                "filter.tags": ["urn:tag:category:place:stationery_store"],
            }},
        ]
    })
    with httpx.Client(transport=_handler(content)) as client:
        plan = draft_plan_llm(
            "k", "m",
            ["Mock Studio Notebooks"], "urn:tag:category:place:stationery_store",
            client=client,
        )
    assert plan.calls[0].params == {"query": "Mock Studio Notebooks"}
    assert plan.calls[1].params["filter.tags"] == "urn:tag:category:place:stationery_store"


def test_plan_params_int_normalized_to_string() -> None:
    content = json.dumps({
        "calls": [{"endpoint": "search", "params": {"query": 42}}]
    })
    with httpx.Client(transport=_handler(content)) as client:
        plan = draft_plan_llm("k", "m", ["x"], None, client=client)
    assert plan.calls[0].params["query"] == "42"


def test_plan_off_allowlist_param_rounded_up_to_rejection() -> None:
    # Off-allowlist keys are still rejected — normalization cannot smuggle keys in.
    from app.agents.researcher import PlanRejectedError
    import pytest

    content = json.dumps({
        "calls": [{"endpoint": "search", "params": {"evil_url": "https://x.test"}}]
    })
    with httpx.Client(transport=_handler(content)) as client:
        import pytest
        with pytest.raises(PlanRejectedError):
            draft_plan_llm("k", "m", ["x"], None, client=client)


_BARE_CLAIM = {
    "claim_id": "claim-A", "concept_id": "A", "claim_type": "observation",
    "strength": "moderate", "confidence": "medium",
    "text": "Mock A ranks second on available evidence.",
    "evidence_ids": [], "score_fields": [], "audience_context": None,
}


def test_strength_medium_synonym_normalized() -> None:
    # Live-found: models sometimes write strength:'medium' (confidence's value
    # bleeding into strength). The ONLY unambiguous synonym is medium→moderate;
    # it is bridged transport-side. Anything else stays a hard rejection.
    bad = {**_BARE_CLAIM, "strength": "medium"}
    content = json.dumps([bad])
    from app.agents.analyst import draft_claims_llm

    with httpx.Client(transport=_handler(content)) as client:
        draft = draft_claims_llm(
            "k", "m",
            {"A": {"rank": 1, "status": "RANKED", "weighted_total": 60.0}},
            {"A": {"available": 5, "total": 5}},
            [], {"c1": 1.0},
            client=client,
        )
    assert [c.strength for c in draft.claims] == ["moderate"]


def test_strength_outword_value_still_rejected() -> None:
    bogus = {**_BARE_CLAIM, "strength": "rock-solid"}
    content = json.dumps([bogus])
    from pydantic import ValidationError as PydanticValidationError
    from app.agents.analyst import draft_claims_llm

    with httpx.Client(transport=_handler(content)) as client:
        import pytest
        with pytest.raises(PydanticValidationError):
            draft_claims_llm(
                "k", "m",
                {"A": {"rank": 1, "status": "RANKED", "weighted_total": 60.0}},
                {"A": {"available": 5, "total": 5}},
                [], {"c1": 1.0},
                client=client,
            )


def test_bare_top_level_claims_array_bridges_into_valid_draft() -> None:
    # Google gemma-4-26b live behavior: answers the claims prompt with a bare
    # JSON array instead of {"claims": [...]}. Bridge + pydantic validation.
    content = json.dumps([_BARE_CLAIM, {**_BARE_CLAIM, "claim_id": "claim-B",
                                        "concept_id": "B"}])
    from app.agents.analyst import draft_claims_llm

    with httpx.Client(transport=_handler(content)) as client:
        draft = draft_claims_llm(
            "k", "m",
            {"A": {"rank": 1, "status": "RANKED", "weighted_total": 60.0}},
            {"A": {"available": 5, "total": 5}},
            [], {"c1": 1.0},
            client=client,
        )
    assert [c.claim_id for c in draft.claims] == ["claim-A", "claim-B"]


def test_bare_top_level_findings_array_bridges_into_valid_output() -> None:
    content = json.dumps([{
        "issue_code": "UNSUPPORTED_CLAIM", "severity": "minor",
        "affected_concept_id": "A", "affected_claim_id": "claim-A",
        "evidence_ids": [], "explanation": "no evidence row backs the phrasing",
        "suggested_action": "qualify",
    }])
    from app.agents.analyst import review_claims_llm

    with httpx.Client(transport=_handler(content)) as client:
        out = review_claims_llm(
            "k", "m", [_BARE_CLAIM],
            {"A": {"rank": 1, "status": "RANKED", "weighted_total": 60.0}},
            [], client=client,
        )
    assert [f.affected_claim_id for f in out.findings] == ["claim-A"]
