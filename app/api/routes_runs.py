"""HTTP routes (Level B): health + decision runs. Thin over the coordinator."""

from __future__ import annotations

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
from app.schemas.brief import DecisionBrief
from app.services.persistence import get_run_bundle
from app.services.rate_limiter import RateLimitExceeded, get_run_limiter
from app.workflow.coordinator import run_decision

router = APIRouter()

# The database was unreachable (DNS/network blip). The message says what
# happened and what the user should do, and never leaks the connection
# string or any credential.
DB_UNAVAILABLE_DETAIL = (
    "The screening run could not be saved because the database was unreachable. "
    "Nothing was stored, so this result was lost. Please run it again."
)


class RunDeps:
    """Per-app dependencies (plain holder, not a schema)."""

    def __init__(self, engine: Engine, source: EvidenceSource, scoring_version: str = "v0.1") -> None:
        self.engine = engine
        self.source = source
        self.scoring_version = scoring_version


def get_deps() -> RunDeps:  # replaced per app instance via dependency_overrides
    raise RuntimeError("app dependencies not configured")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/decision-runs")
def post_run(brief: DecisionBrief, deps: RunDeps = Depends(get_deps)) -> dict[str, Any]:
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
        # G3 LLM hooks follow the two-pool Settings (LLM_ENABLED gate). When
        # enabled-but-misconfigured, fail the request loudly: a silent template
        # fallback would quietly misrepresent the run's evidence quality.
        llm_hooks = None
        settings = Settings.from_env()
        if settings.llm_enabled:
            from app.services.llm_hooks import build_hooks

            llm_hooks = build_hooks(
                settings,
                [(c.concept_id, c.name) for c in brief.concepts],
            )
        try:
            return run_decision(
                deps.engine,
                brief,
                deps.source,
                scoring_version=deps.scoring_version,
                **(llm_hooks or {}),
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


@router.get("/decision-runs/{run_id}")
def get_run(run_id: str, deps: RunDeps = Depends(get_deps)) -> dict[str, Any]:
    try:
        return get_run_bundle(deps.engine, run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="unknown run_id") from None
    except (InvalidatePoolError, OperationalError, InterfaceError) as exc:
        raise HTTPException(status_code=503, detail=DB_UNAVAILABLE_DETAIL) from exc


__all__ = ["router", "get_deps", "RunDeps"]
