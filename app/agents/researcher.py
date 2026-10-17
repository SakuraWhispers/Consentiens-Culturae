"""Researcher: LLM proposes a retrieval plan; code enforces allowlist + budget."""

from __future__ import annotations

from typing import Any

from app.agents.schemas import ALLOWED_PARAMS, ALLOWLISTED_ENDPOINTS, RetrievalPlan


class PlanRejectedError(ValueError):
    """Raised when the coordinator must reject a researcher plan."""


def validate_plan(plan: RetrievalPlan, max_calls: int = 10) -> RetrievalPlan:
    """Code-side enforcement. Rejects anything off-allowlist or over budget."""
    if len(plan.calls) > max_calls:
        raise PlanRejectedError(f"plan exceeds call budget: {len(plan.calls)} > {max_calls}")
    for call in plan.calls:
        if call.endpoint not in ALLOWLISTED_ENDPOINTS:
            raise PlanRejectedError(f"endpoint {call.endpoint!r} is not on the allowlist")
        allowed = ALLOWED_PARAMS[call.endpoint]
        for key in call.params:
            if key not in allowed:
                raise PlanRejectedError(f"param {key!r} not allowed for {call.endpoint}")
            value = call.params[key]
            if isinstance(value, str) and not value.strip():
                raise PlanRejectedError(
                    f"empty value for param {key!r} on {call.endpoint} "
                    "(Qloo silently ignores bad params — rejected to protect evidence)"
                )
        if (
            call.endpoint == "insights"
            and "filter.type" not in call.params
        ):
            raise PlanRejectedError(
                "insights call missing required 'filter.type' param "
                "(Qloo docs: required; invalid params are silently ignored)"
            )
        if call.endpoint == "insights" and call.params.get("filter.type") not in (
            None,
            "urn:entity:place",
        ):
            # Only the docs-verified type (docs/qloo-api-notes.md) produces the
            # place-level evidence this pipeline scores; anything else seeds a
            # 200-plus-dead-evidence insights call instead of a loud failure.
            raise PlanRejectedError(
                f"insights filter.type {call.params.get('filter.type')!r} is not "
                "the docs-verified 'urn:entity:place' for this pipeline"
            )
    return plan


def researcher_fallback(concept_names: list[str], tag_urn: str | None) -> RetrievalPlan:
    """Deterministic planner: search per concept + one shared insights call."""
    calls: list[dict[str, Any]] = [{"endpoint": "search", "params": {"query": n}} for n in concept_names]
    if tag_urn:
        calls.append(
            {"endpoint": "insights", "params": {"filter.type": "urn:entity:place", "filter.tags": tag_urn}}
        )
    return validate_plan(RetrievalPlan(calls=calls))


__all__ = ["PlanRejectedError", "validate_plan", "researcher_fallback"]
