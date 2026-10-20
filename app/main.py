"""FastAPI app (Level B). One process serving API (+ static UI later)."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from app.api.routes_runs import RunDeps, get_deps, router
from app.config import Settings
from app.integrations.qloo_adapter import FixtureSource, LiveEvidenceSource
from app.integrations.qloo_client import QlooClient
from app.services.persistence import get_engine, init_db

STATIONERY_TAG_URN = "urn:tag:category:place:stationery_store"


def create_app(
    database_url: str | None = None,
    app_mode: str | None = None,
    fixtures_dir: Path | None = None,
    scoring_version: str = "v0.1",
) -> FastAPI:
    settings = Settings.from_env()
    database_url = database_url or settings.database_url
    app_mode = (app_mode or settings.app_mode).lower()

    engine = get_engine(database_url)
    init_db(engine)

    if app_mode == "live":
        api_key = os.environ.get("QLOO_API_KEY", "")
        if not api_key:
            raise RuntimeError("APP_MODE=live requires QLOO_API_KEY in the environment")
        client = QlooClient(
            base_url=settings.qloo_base_url,
            api_key=api_key,
            timeout_seconds=settings.qloo_timeout_seconds,
        )
        source = LiveEvidenceSource(client, tag_urn=STATIONERY_TAG_URN)
    else:
        source = FixtureSource(fixtures_dir or Path("tests/fixtures"))

    app = FastAPI(title="Consentiens-Culturae Decision Engine")

    # CORS for the Next.js frontend during local development. Origins come from
    # CORS_ORIGINS (comma-separated); the default is the Next dev server only.
    # Never use "*" once real keys exist anywhere — this app has no secrets in
    # the browser, but explicit origins keep future changes deliberate.
    import os

    cors_origins = [
        o.strip() for o in
        os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
        if o.strip()
    ]
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.dependency_overrides[get_deps] = lambda: RunDeps(
        engine=engine, source=source, scoring_version=scoring_version
    )
    app.include_router(router, prefix="/api")
    return app


app = None  # created by the server entrypoint: uvicorn --factory app.main:serve


def serve() -> FastAPI:
    global app
    settings = Settings.from_env()
    problems = settings.validate_for_mode()
    if problems:
        raise RuntimeError("; ".join(problems))
    app = create_app()
    return app


__all__ = ["create_app", "serve"]
