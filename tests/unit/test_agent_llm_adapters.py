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
