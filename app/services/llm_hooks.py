"""G3 LLM hook wiring for the HTTP API path (API parity with the probe).

Pure composition of tested pieces: the llm_client adapters, the researcher
planner, coordinator contracts, and the two-pool Settings from app/config.py.
The only new behavior is the transient-error paced retry shared by all hooks
(free-pool 429s and Google 5xx blips waste instant retries; 2026-10-17 finding)
and the owner attribution for search calls (probe logic, extracted).

No exception is silently swallowed: what the hooks fail on, the coordinator
records as a run limitation and the deterministic path takes over. Missing
keys when LLM_ENABLED=true raise loudly (Route: no quiet budget lies).

Secret handling: keys travel to the configured endpoints inside request
headers only; they are never logged, printed, or embedded in results.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import httpx  # noqa: F401  (kept: explicit dependency for provider timeouts)

from app.agents.analyst import (
    AnalysisDraft,
    CriticOutput,
    RetrievalPlan,
    compare_tied_llm,
    draft_claims_llm,
    draft_concept_notes_llm,
    draft_plan_llm,
    draft_report_llm,
    review_claims_llm,
    revise_claims_llm,
)
from app.agents.llm_client import AgentLLMError
from app.agents.schemas import AgentOutput
from app.config import Settings, llm_api_key as _llm_api_key

TRANSIENT_MARKERS = ("rate limited", "HTTP 5", "UNAVAILABLE", "Internal error")


def paced(fn: Callable[..., Any], *, wait_seconds: float = 70.0) -> Callable[..., Any]:
    """Wrap one hook call with a single paced retry on transient errors.

    The coordinator runs each hook at most twice (its own retry-once); this
    wrapper adds at most one 70s pause between provider-side 429/5xx so an
    instant re-hit of a saturated pool is not wasted. Non-transient errors
    (schema, auth, semantics) re-raise untouched.
    """

    def call(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except AgentLLMError as exc:
            if not any(m in str(exc) for m in TRANSIENT_MARKERS):
                raise
        time.sleep(wait_seconds)
        return fn(*args, **kwargs)

    return call


def resolve_pools(settings: Settings) -> dict[str, dict[str, Any]]:
    """Resolve the two pools' model/base/key/generation from Settings.

    Generation budgets are the live-bisected values (2026-10-17/19 findings):
    OpenRouter keeps its reasoning-budget dance; Google's compat layer 500s
    above max_tokens 16384 and does not accept the OpenRouter `reasoning` key.
    """
    base_url = settings.llm_base_url
    on_google = "generativelanguage" in base_url
    on_openrouter = "openrouter" in base_url
    if on_google:
        main_gen: dict[str, Any] = {"max_tokens": 16384}
    elif on_openrouter:
        main_gen = {"max_tokens": 24000, "reasoning": {"effort": "high"}}
    else:
        main_gen = {"max_tokens": 24000}

    researcher_base = settings.researcher_base_url()
    res_on_google = "generativelanguage" in researcher_base
    res_on_openrouter = "openrouter" in researcher_base
    if res_on_openrouter:
        researcher_gen: dict[str, Any] = {
            "max_tokens": 32768,
            "reasoning": {"max_tokens": 16384},
        }
    elif res_on_google:
        researcher_gen = {"max_tokens": 16384}
    else:
        researcher_gen = {"max_tokens": 32768}

    # The suggester answers with a handful of short attribute pairs; a small
    # budget is plenty (and respects Google's <= 16384 rule).
    suggester_base = settings.llm_suggester_base_url or base_url
    sug_on_google = "generativelanguage" in suggester_base
    suggester_gen: dict[str, Any] = {"max_tokens": 2048 if sug_on_google else 4096}

    return {
        "main": {
            "model": settings.llm_model,
            "base_url": base_url,
            "api_key": _llm_api_key(settings.llm_provider),
            "gen": main_gen,
        },
        "researcher": {
            "model": settings.llm_researcher_model or settings.llm_model,
            "base_url": researcher_base,
            "api_key": settings.researcher_api_key(),
            "gen": researcher_gen,
        },
        "suggester": {
            "model": settings.llm_suggester_model or settings.llm_model,
            "base_url": suggester_base,
            "api_key": _llm_api_key(settings.llm_provider),
            "gen": suggester_gen,
        },
    }


def attribute_search_calls(
    calls: list[dict[str, Any]], concepts: list[tuple[str, str]]
) -> list[tuple[Any, str, dict[str, str]]]:
    """Attach owner attribution to a validated plan's calls (probe logic).

    A search whose query matches exactly one concept name belongs to that
    concept; everything else is shared market evidence. The coordinator
    enforces the allowlist and call budget on the returned tuples.
    """
    lowered = {name.lower(): cid for cid, name in concepts if name}
    out: list[tuple[Any, str, dict[str, str]]] = []
    for call in calls:
        owner = None
        if call["endpoint"] == "search":
            q = (call["params"].get("query") or "").lower()
            hits = [cid for name, cid in lowered.items() if name in q]
            if len(hits) == 1:
                owner = hits[0]
        out.append((owner, call["endpoint"], dict(call["params"])))
    return out


def build_hooks(
    settings: Settings, concepts: list[tuple[str, str]]
) -> dict[str, Callable[..., Any]]:
    """Build the four coordinators hooks from the two-pool configuration.

    `concepts` is the brief's [(concept_id, name), ...] list, used for search
    ownership attribution. Raises loudly when LLM is enabled but a pool has
    no key — misconfiguration must be loud, never a silent template fallback.
    """
    if not settings.llm_enabled:
        raise ValueError("LLM is not enabled")
    pools = resolve_pools(settings)
    main_key = pools["main"]["api_key"]
    researcher_key = pools["researcher"]["api_key"]
    missing = [
        pool for pool, key in (("main", main_key), ("researcher", researcher_key))
        if not key
    ]
    if missing:
        raise ValueError(
            f"LLM_ENABLED=true but no API key for pool(s): {', '.join(missing)}"
        )

    m = pools["main"]
    r = pools["researcher"]
    # Reasoning-heavy calls routinely exceed the 30s default; the live floor
    # for paced Google calls is 300s (probe: analyst still generating at 180s).
    timeout = max(settings.llm_timeout_seconds, 300.0)

    def researcher_fn(
        names: list[str], category_hint: str | None, repair_hint: str | None = None
    ) -> AgentOutput:
        def once() -> RetrievalPlan:
            return draft_plan_llm(
                researcher_key, r["model"], names, category_hint,
                timeout=timeout, base_url=r["base_url"],
                max_tokens=r["gen"]["max_tokens"], reasoning=r["gen"].get("reasoning"),
                repair_hint=repair_hint,
            )

        plan = paced(once)()
        return AgentOutput(
            items=attribute_search_calls(
                [c.model_dump() for c in plan.calls], concepts
            ),
            rejected=list(plan.rejected),
            raw_head=plan.raw_head,
            category=plan.category,
        )

    def analyst_fn(
        score_summary: dict[str, Any],
        evidence_summary: dict[str, Any],
        limitations: list[str],
        weights: dict[str, float],
        repair_hint: str | None = None,
    ) -> AgentOutput:
        def once() -> AnalysisDraft:
            draft: AnalysisDraft = draft_claims_llm(
                main_key, m["model"], score_summary, evidence_summary,
                limitations, weights,
                timeout=timeout, base_url=m["base_url"],
                max_tokens=m["gen"]["max_tokens"], reasoning=m["gen"].get("reasoning"),
                repair_hint=repair_hint,
            )
            return draft

        draft = paced(once)()
        return AgentOutput(
            items=[c.model_dump() for c in draft.claims],
            rejected=list(draft.rejected),
            raw_head=draft.raw_head,
        )

    def critic_fn(
        claims: list[dict[str, Any]],
        score_summary: dict[str, Any],
        known_ids: list[str],
        repair_hint: str | None = None,
    ) -> AgentOutput:
        def once() -> CriticOutput:
            return review_claims_llm(
                main_key, m["model"], claims, score_summary, sorted(known_ids),
                timeout=timeout, base_url=m["base_url"],
                max_tokens=m["gen"]["max_tokens"], reasoning=m["gen"].get("reasoning"),
                repair_hint=repair_hint,
            )

        out = paced(once)()
        return AgentOutput(
            items=[f.model_dump() for f in out.findings],
            rejected=list(out.rejected),
            raw_head=out.raw_head,
        )

    def revise_fn(
        claims: list[dict[str, Any]],
        findings: list[dict[str, Any]],
        repair_hint: str | None = None,
    ) -> AgentOutput:
        def once() -> AnalysisDraft:
            return revise_claims_llm(
                main_key, m["model"], claims, findings,
                timeout=timeout, base_url=m["base_url"],
                max_tokens=m["gen"]["max_tokens"], reasoning=m["gen"].get("reasoning"),
                repair_hint=repair_hint,
            )

        out = paced(once)()
        return AgentOutput(
            items=[c.model_dump() for c in out.claims],
            rejected=list(out.rejected),
            raw_head=out.raw_head,
        )

    def tiebreak_fn(
        tied: list[dict[str, Any]],
        evidence_summary: dict[str, Any],
        weights: dict[str, float],
        before: dict[str, float],
        after: dict[str, float],
        repair_hint: str | None = None,
    ) -> AgentOutput:
        """The focused comparison of the concepts the scoring left level."""

        def once() -> AnalysisDraft:
            return compare_tied_llm(
                main_key, m["model"], tied, evidence_summary, weights, before, after,
                timeout=timeout, base_url=m["base_url"],
                max_tokens=m["gen"]["max_tokens"], reasoning=m["gen"].get("reasoning"),
                repair_hint=repair_hint,
            )

        out = paced(once)()
        return AgentOutput(
            items=[c.model_dump() for c in out.claims],
            rejected=list(out.rejected),
            raw_head=out.raw_head,
        )

    def reporter_fn(
        payload: dict[str, Any],
        repair_hint: str | None = None,
    ) -> dict[str, Any]:
        """The verbose report (Batch 3): prose, written only after the
        critique succeeded; the coordinator's number guard judges it."""

        def once() -> str:
            return draft_report_llm(
                main_key, m["model"], payload,
                timeout=timeout, base_url=m["base_url"],
                max_tokens=m["gen"]["max_tokens"], reasoning=m["gen"].get("reasoning"),
                repair_hint=repair_hint,
            )

        return {"report": paced(once)()}

    def concept_critic_fn(
        payload: dict[str, Any],
        repair_hint: str | None = None,
    ) -> dict[str, Any]:
        """The per-concept critique notes (2026-10-24): drawbacks per concept
        plus a 5-6 line winning-concept note. One extra paced call per run;
        the coordinator's guards (ids, cap, number guard) judge the output."""

        def once() -> dict[str, Any]:
            return draft_concept_notes_llm(
                main_key, m["model"], payload,
                timeout=timeout, base_url=m["base_url"],
                max_tokens=m["gen"]["max_tokens"], reasoning=m["gen"].get("reasoning"),
                repair_hint=repair_hint,
            )

        return paced(once)()

    return {
        "researcher_fn": researcher_fn,
        "analyst_fn": analyst_fn,
        "critic_fn": critic_fn,
        "revise_fn": revise_fn,
        "tiebreak_fn": tiebreak_fn,
        "reporter_fn": reporter_fn,
        "concept_critic_fn": concept_critic_fn,
    }


__all__ = ["build_hooks", "paced", "resolve_pools", "attribute_search_calls"]
