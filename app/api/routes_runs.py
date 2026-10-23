"""HTTP routes (Level B): health + decision runs. Thin over the coordinator."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.engine import Engine
from sqlalchemy.exc import (
    InterfaceError,
    InvalidatePoolError,
    OperationalError,
)

from app.config import Settings
from app.integrations.qloo_adapter import EvidenceSource
from app.schemas.brief import AttributeSuggestionRequest, DecisionBrief
from app.services.persistence import (
    create_run,
    delete_run,
    get_run_bundle,
    get_run_input,
    get_run_state,
)
from app.services.rate_limiter import RateLimitExceeded, get_run_limiter
from app.agents.analyst import suggest_attributes_llm
from app.workflow.coordinator import preflight_constraint_check, run_decision
from app.workflow.states import TERMINAL_STATES, RunState

router = APIRouter()

# The database was unreachable (DNS/network blip). The message says what
# happened and what the user should do, and never leaks the connection
# string or any credential.
DB_UNAVAILABLE_DETAIL = (
    "The screening run could not be saved because the database was unreachable. "
    "Nothing was stored, so this result was lost. Please run it again."
)


class RunRequest(DecisionBrief):
    """The brief plus an optional client-chosen run id.

    The client may generate the id so it can watch the run's progress (and
    find it again) before the pipeline returns. The server validates the
    format and refuses an id that already exists.
    """

    run_id: str | None = None


class RunDeps:
    """Per-app dependencies (plain holder, not a schema)."""

    def __init__(self, engine: Engine, source: EvidenceSource, scoring_version: str = "v0.1") -> None:
        self.engine = engine
        self.source = source
        self.scoring_version = scoring_version


def get_deps() -> RunDeps:  # replaced per app instance via dependency_overrides
    raise RuntimeError("app dependencies not configured")


def _validated_run_id(candidate: str | None) -> str:
    """Accept a client-supplied run id only in the exact shape we generate."""
    if candidate is None:
        return uuid.uuid4().hex
    if len(candidate) != 32 or any(c not in "0123456789abcdef" for c in candidate):
        raise HTTPException(
            status_code=422, detail="run_id must be 32 lowercase hex characters"
        )
    return candidate


def _llm_hooks(brief: DecisionBrief) -> dict[str, Any]:
    """Build the G3 hooks when the LLM is enabled; fail loudly if misconfigured."""
    settings = Settings.from_env()
    if not settings.llm_enabled:
        return {}
    from app.services.llm_hooks import build_hooks

    return build_hooks(
        settings,
        [(c.concept_id, c.name) for c in brief.concepts],
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/decision-runs")
def post_run(request: RunRequest, deps: RunDeps = Depends(get_deps)) -> dict[str, Any]:
    # Run limiter (free-model budget protection): one at a time, min gap,
    # daily cap. 429 carries Retry-After; the UI surfaces it verbatim.
    limiter = get_run_limiter()
    try:
        limiter.acquire()
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    try:
        brief = DecisionBrief(**request.model_dump(exclude={"run_id"}))
        run_id = _validated_run_id(request.run_id)
        try:
            llm_hooks = _llm_hooks(brief)
        except ValueError as exc:
            if "LLM_ENABLED" in str(exc):
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            raise
        try:
            # Pre-flight (2026-10-23): name every constraint that could never
            # be checked BEFORE the run row exists or any call is paid for.
            preflight_constraint_check(brief)
            # The run row exists BEFORE the pipeline starts, so the client
            # (which may know the id already) can follow its progress and
            # find it again if the request dies.
            create_run(
                deps.engine,
                input_json=brief.model_dump(),
                scoring_version=deps.scoring_version,
                workflow_version="w0.1-g2",
                run_id=run_id,
            )
            return run_decision(
                deps.engine,
                brief,
                deps.source,
                scoring_version=deps.scoring_version,
                run_id=run_id,
                **llm_hooks,
            )
        except ValueError as exc:
            # Distinguish hook misconfiguration from brief-contract rejects so
            # neither hides the other.
            if "LLM_ENABLED" in str(exc):
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (InvalidatePoolError, OperationalError, InterfaceError) as exc:
            # The database was unreachable (2026-10-21: a DNS blip killed a
            # live run at its last write). Say so plainly — a bare 500 gave
            # the user nothing to act on.
            raise HTTPException(status_code=503, detail=DB_UNAVAILABLE_DETAIL) from exc
    finally:
        limiter.release()


@router.post("/attributes/suggest")
def suggest_attributes(
    request: AttributeSuggestionRequest, deps: RunDeps = Depends(get_deps)
) -> dict[str, Any]:
    """Cheap pre-run assist (2026-10-23): propose attribute values grounded in
    each concept's description. The user copies what they agree with; nothing
    is auto-applied and the constraint gate stays deterministic code. Not
    run-limited (one short call, no Qloo, no run row), but LLM-mode only -
    a fixture-mode service must not fake model suggestions."""
    settings = Settings.from_env()
    if not settings.llm_enabled:
        raise HTTPException(
            status_code=503,
            detail="the attribute suggester needs LLM mode (LLM_ENABLED=true)",
        )
    from app.services.llm_hooks import resolve_pools

    pool = resolve_pools(settings)["suggester"]
    if not pool["api_key"]:
        raise HTTPException(
            status_code=503, detail="no API key configured for the suggester"
        )
    try:
        kept, rejected = suggest_attributes_llm(
            pool["api_key"],
            pool["model"],
            [c.model_dump() for c in request.concepts],
            [a.strip()[:40] for a in request.target_attributes if a.strip()],
            timeout=settings.llm_timeout_seconds,
            base_url=pool["base_url"],
            max_tokens=pool["gen"]["max_tokens"],
            reasoning=pool["gen"].get("reasoning"),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"suggester failed: {str(exc)[:200]}"
        ) from exc
    return {"suggestions": kept, "rejected": rejected}


@router.post("/decision-runs/{run_id}/resume")
def resume_run(run_id: str, deps: RunDeps = Depends(get_deps)) -> dict[str, Any]:
    """Continue a half-finished run in place, reusing its stored evidence.

    The Qloo calls are NOT repeated (the evidence is already stored), so a
    resume costs no Qloo quota; the analysis stages run again.
    """
    limiter = get_run_limiter()
    try:
        limiter.acquire()
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    try:
        try:
            state_value, _ = get_run_state(deps.engine, run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="unknown run_id") from exc
        if state_value in {s.value for s in TERMINAL_STATES}:
            raise HTTPException(
                status_code=409,
                detail=f"run already finished ({state_value}); nothing to resume",
            )
        try:
            brief = DecisionBrief(**get_run_input(deps.engine, run_id))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            llm_hooks = _llm_hooks(brief)
        except ValueError as exc:
            if "LLM_ENABLED" in str(exc):
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            raise
        try:
            return run_decision(
                deps.engine,
                brief,
                deps.source,
                scoring_version=deps.scoring_version,
                run_id=run_id,
                restore_evidence=True,
                **llm_hooks,
            )
        except ValueError as exc:
            if "LLM_ENABLED" in str(exc):
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (InvalidatePoolError, OperationalError, InterfaceError) as exc:
            raise HTTPException(status_code=503, detail=DB_UNAVAILABLE_DETAIL) from exc
    finally:
        limiter.release()


@router.delete("/decision-runs/{run_id}")
def delete_run_endpoint(run_id: str, deps: RunDeps = Depends(get_deps)) -> dict[str, Any]:
    """Delete a run and its rows — the 'start fresh' cleanup.

    Only the rows of THIS run are deleted. A completed run can be deleted too
    (the user asked for it explicitly).
    """
    try:
        deleted = delete_run(deps.engine, run_id)
    except (InvalidatePoolError, OperationalError, InterfaceError) as exc:
        raise HTTPException(status_code=503, detail=DB_UNAVAILABLE_DETAIL) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="unknown run_id")
    return {"run_id": run_id, "deleted": True}


@router.get("/decision-runs/{run_id}")
def get_run(run_id: str, deps: RunDeps = Depends(get_deps)) -> dict[str, Any]:
    try:
        return get_run_bundle(deps.engine, run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="unknown run_id") from None
    except (InvalidatePoolError, OperationalError, InterfaceError) as exc:
        raise HTTPException(status_code=503, detail=DB_UNAVAILABLE_DETAIL) from exc


__all__ = ["router", "get_deps", "RunDeps", "RunRequest"]
