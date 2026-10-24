"""Researcher: LLM proposes a retrieval plan; code enforces allowlist + budget.

The rules live in ONE place (`validate_call`) and are applied per call, so a
single malformed call no longer discards the whole plan: `salvage_calls`
keeps the calls that satisfy the rules and reports the ones that do not.
The live failure this fixes (2026-10-20, run c2b65018…): the model wrote a
param named "filter", the whole plan was rejected, and the deterministic
planner took over.
"""

from __future__ import annotations

from typing import Any

from app.agents.schemas import ALLOWED_PARAMS, ALLOWLISTED_ENDPOINTS, RetrievalPlan


class PlanRejectedError(ValueError):
    """Raised when the coordinator must reject a researcher plan."""


def validate_call(endpoint: str, params: dict[str, str]) -> list[str]:
    """Rule violations for ONE planned call (empty list = acceptable).

    The rules are the same ones the pipeline has always enforced: allowlisted
    endpoint, allowlisted param keys, no empty values. Since 2026-10-24 the
    researcher's vocabulary is search-only: the market-level insights call is
    planned by CODE from the category the researcher named, because a
    model-written filter.tags URN would be an invented identifier.

    Returning every violation instead of raising on the first one lets
    the caller drop just this call and keep the rest of the plan.
    """
    errors: list[str] = []
    if endpoint not in ALLOWLISTED_ENDPOINTS:
        if endpoint in ("insights", "tags"):
            errors.append(
                f"endpoint {endpoint!r} is planned by the code itself: name a "
                "category instead (filter.tags URNs from a model are "
                "invented identifiers)"
            )
        else:
            errors.append(f"endpoint {endpoint!r} is not on the allowlist")
        return errors
    allowed = ALLOWED_PARAMS[endpoint]
    for key, value in params.items():
        if key not in allowed:
            errors.append(f"param {key!r} not allowed for {endpoint}")
            continue
        if isinstance(value, str) and not value.strip():
            errors.append(
                f"empty value for param {key!r} on {endpoint} "
                "(Qloo silently ignores bad params — rejected to protect evidence)"
            )
    return errors


def salvage_calls(
    calls: list[dict[str, Any]], max_calls: int = 10
) -> tuple[list[dict[str, Any]], list[str]]:
    """Per-call validation: keep the calls that pass, report the ones that do not.

    Returns (kept_calls, rejected_notes). No call is ever silently dropped:
    every rejection is reported so the coordinator can name it as a run
    limitation.
    """
    kept: list[dict[str, Any]] = []
    rejected: list[str] = []
    for index, call in enumerate(calls):
        endpoint = str(call.get("endpoint", ""))
        params = call.get("params") or {}
        errors = validate_call(endpoint, params)
        if errors:
            rejected.append(f"call {index + 1} ({endpoint or 'no endpoint'}) rejected: {errors[0]}")
            continue
        kept.append({"endpoint": endpoint, "params": dict(params)})
    if len(kept) > max_calls:
        rejected.append(f"plan truncated to call budget: {len(kept)} > {max_calls}")
        kept = kept[:max_calls]
    return kept, rejected


def validate_plan(plan: RetrievalPlan, max_calls: int = 10) -> RetrievalPlan:
    """Code-side enforcement. Rejects anything off-allowlist or over budget."""
    if len(plan.calls) > max_calls:
        raise PlanRejectedError(f"plan exceeds call budget: {len(plan.calls)} > {max_calls}")
    for call in plan.calls:
        errors = validate_call(call.endpoint, call.params)
        if errors:
            raise PlanRejectedError(errors[0])
    return plan


def researcher_fallback(concept_names: list[str], tag_urn: str | None = None) -> RetrievalPlan:
    """Deterministic planner: one search per concept.

    Since 2026-10-24 this returns SEARCH calls only: the category→tag URN
    resolution and the shared market insights call are code-planned in the
    coordinator (live) or omitted in fixture mode (the loader serves
    search fixtures only). `tag_urn` stays accepted for script callers.
    """
    calls: list[dict[str, Any]] = [{"endpoint": "search", "params": {"query": n}} for n in concept_names]
    return validate_plan(RetrievalPlan(calls=calls))


__all__ = [
    "PlanRejectedError",
    "validate_call",
    "salvage_calls",
    "validate_plan",
    "researcher_fallback",
]
