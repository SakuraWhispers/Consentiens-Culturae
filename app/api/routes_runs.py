"""HTTP routes (Level B): health + decision runs. Thin over the coordinator."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.engine import Engine

from app.integrations.qloo_adapter import EvidenceSource
from app.schemas.brief import DecisionBrief
from app.services.persistence import get_run_bundle
from app.workflow.coordinator import run_decision

router = APIRouter()


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
    try:
        return run_decision(deps.engine, brief, deps.source, scoring_version=deps.scoring_version)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/decision-runs/{run_id}")
def get_run(run_id: str, deps: RunDeps = Depends(get_deps)) -> dict[str, Any]:
    try:
        return get_run_bundle(deps.engine, run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="unknown run_id") from None


__all__ = ["router", "get_deps", "RunDeps"]
