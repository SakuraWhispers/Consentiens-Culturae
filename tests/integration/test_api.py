"""API tests (Level B): health, run creation, validation, retrieval. Offline."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.rate_limiter import reset_run_limiter


@pytest.fixture(autouse=True)
def _fresh_run_limiter():
    # The limiter is process-global by design; each test gets a clean one so
    # the 30s start-gap and daily cap cannot leak between tests.
    reset_run_limiter()
    yield
    reset_run_limiter()


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _brief_dict() -> dict:
    return {
        "market": "US, online and indie bookstores",
        "audience_description": "Design-conscious note-takers aged 18-35",
        "business_goal": "Pick one of three concepts for a limited holiday run",
        "constraints": [
            {"attribute": "material", "value": "recycled"},
            {"attribute": "price_band", "value": "under-25"},
            {"attribute": "product_type", "value": "stationery"},
        ],
        "weights": {"c1": 0.35, "c2": 0.20, "c3": 0.25, "c5": 0.20},
        "concepts": [
            {
                "concept_id": "A",
                "name": "Mock Studio Notebooks",
                "description": "Recycled notebook",
                "attributes": {"material": "recycled", "price_band": "under-25", "product_type": "stationery"},
            },
            {
                "concept_id": "B",
                "name": "Mock Luxury Pen",
                "description": "Over-budget pen",
                "attributes": {"material": "virgin-plastic", "price_band": "over-100", "product_type": "stationery"},
            },
            {
                "concept_id": "C",
                "name": "Mock Desk Organizer",
                "description": "Fiber organizer",
                "attributes": {"material": "recycled", "price_band": "under-25", "product_type": "stationery"},
            },
        ],
    }


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        database_url=f"sqlite:///{tmp_path}/api_test.db",
        app_mode="fixture",
        fixtures_dir=FIXTURES_DIR,
    )
    return TestClient(app)


def test_duplicate_run_id_with_a_different_brief_is_refused(
    tmp_path: Path, monkeypatch
) -> None:
    """Audit fix (2026-10-23): re-POSTing an existing run_id with a changed
    brief must be refused - the first run's stored report must survive
    untouched (no silent overwrite, no mixed evidence)."""
    monkeypatch.setenv("RUN_MIN_GAP_SECONDS", "0")  # two back-to-back POSTs
    reset_run_limiter()
    run_id = uuid.uuid4().hex
    with _client(tmp_path) as client:
        first = client.post("/api/decision-runs", json=_brief_dict() | {"run_id": run_id})
        assert first.status_code == 200, first.text
        before = client.get(f"/api/decision-runs/{run_id}").json()
        changed = _brief_dict() | {"run_id": run_id, "market": "Porto, Portugal"}
        second = client.post("/api/decision-runs", json=changed)
        assert second.status_code == 422, second.text
        assert "different brief" in second.json()["detail"]
        after = client.get(f"/api/decision-runs/{run_id}").json()
    assert after["run"]["input_json"]["market"] == before["run"]["input_json"]["market"]
    assert after["run"]["final_report_json"] == before["run"]["final_report_json"]


def test_cannot_check_constraint_rejects_with_422_detail(tmp_path: Path) -> None:
    """Pre-flight (2026-10-23): before any spend, a constraint naming an
    attribute no concept declares must come back as 422 naming the concept -
    never as a surprise INFEASIBLE result four minutes later."""
    payload = _brief_dict()
    payload["concepts"][0]["attributes"].pop("material", None)  # A loses 'material'
    with _client(tmp_path) as client:
        response = client.post("/api/decision-runs", json=payload)
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert "'material'" in detail
    assert "A" in detail


def test_preflight_422_does_not_burn_a_run_slot(tmp_path: Path, monkeypatch) -> None:
    """Audit fix (2026-10-23): the slot was taken before validation, so a
    rejected brief consumed one of the day's runs AND settled the 30 s gap.
    Validation (and cheap refusals) must come first."""
    monkeypatch.setenv("RUNS_PER_DAY", "2")
    monkeypatch.setenv("RUN_MIN_GAP_SECONDS", "0")  # the gap is not what's tested
    reset_run_limiter()
    invalid = _brief_dict()
    invalid["concepts"][0]["attributes"].pop("material", None)
    with _client(tmp_path) as client:
        rejected = client.post("/api/decision-runs", json=invalid)
        assert rejected.status_code == 422, rejected.text
        first = client.post("/api/decision-runs", json=_brief_dict())
        assert first.status_code == 200, first.text  # slot 1: a real run
        second = client.post("/api/decision-runs", json=_brief_dict())
        assert second.status_code == 200, second.text  # slot 2: a real run
        blocked = client.post("/api/decision-runs", json=_brief_dict())
        assert blocked.status_code == 429  # the day cap, not the 422 above
    reset_run_limiter()


def test_resume_of_a_finished_run_does_not_burn_a_run_slot(
    tmp_path: Path, monkeypatch
) -> None:
    """Audit fix (2026-10-23): the 409 for an already-finished run must not
    consume a slot (it used to, before the limiter was moved after lookups)."""
    monkeypatch.setenv("RUNS_PER_DAY", "2")
    monkeypatch.setenv("RUN_MIN_GAP_SECONDS", "0")  # the gap is not what's tested
    reset_run_limiter()
    with _client(tmp_path) as client:
        run_id = client.post("/api/decision-runs", json=_brief_dict()).json()["run_id"]
        again = client.post(f"/api/decision-runs/{run_id}/resume")
        assert again.status_code == 409, again.text  # finished; nothing to resume
        fresh = client.post("/api/decision-runs", json=_brief_dict())
        assert fresh.status_code == 200, fresh.text  # the slot was NOT burned
    reset_run_limiter()


def test_attribute_suggester_needs_llm_mode(tmp_path: Path) -> None:
    payload = {
        "concepts": [
            {"concept_id": "A", "name": "Mock Studio Notebooks", "description": "Recycled notebook", "attributes": {}}
        ],
        "target_attributes": ["material"],
    }
    with _client(tmp_path) as client:  # fixture app_mode, LLM disabled
        response = client.post("/api/attributes/suggest", json=payload)
    assert response.status_code == 503, response.text
    assert "LLM_ENABLED" in response.json()["detail"]


def test_suggester_rate_limit_stops_repeated_clicks(tmp_path: Path, monkeypatch) -> None:
    """Audit fix (2026-10-23): the suggest button spends from the SAME
    free-model budget as runs, so repeated clicking must hit a cap, not
    drain the day's quota."""
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "google")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-for-suggester-only")
    monkeypatch.setenv("SUGGESTS_PER_DAY", "2")
    reset_run_limiter()  # rebuild both singletons from the env above

    def fake_suggest(api_key, model, concepts, target_attributes=None, **kwargs):
        return [{"concept_id": concepts[0]["concept_id"], "attributes": []}], []

    monkeypatch.setattr("app.api.routes_runs.suggest_attributes_llm", fake_suggest)
    payload = {
        "concepts": [
            {"concept_id": "A", "name": "Mock Studio Notebooks", "description": "Recycled notebook", "attributes": {}}
        ],
        "target_attributes": ["material"],
    }
    with _client(tmp_path) as client:
        for expected in (200, 200, 429):
            response = client.post("/api/attributes/suggest", json=payload)
            assert response.status_code == expected, response.text
        assert "Retry-After" in response.headers
    reset_run_limiter()


def test_attribute_suggester_returns_sanitized_proposals(tmp_path: Path, monkeypatch) -> None:
    def fake_suggest(api_key, model, concepts, target_attributes=None, **kwargs):
        assert target_attributes == ["material"]
        kept, rejected = (
            [
                {
                    "concept_id": "A",
                    "attributes": [
                        {"attribute": "material", "value": "recycled", "basis": "stated", "quote": "Recycled notebook"}
                    ],
                }
            ],
            [f"{concepts[0]['concept_id']}: dropped junk"],
        )
        return kept, rejected

    monkeypatch.setattr(
        "app.api.routes_runs.suggest_attributes_llm", fake_suggest
    )
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "google")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-for-suggester-only")
    payload = {
        "concepts": [
            {"concept_id": "A", "name": "Mock Studio Notebooks", "description": "Recycled notebook", "attributes": {}}
        ],
        "target_attributes": ["material"],
    }
    with _client(tmp_path) as client:
        response = client.post("/api/attributes/suggest", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["suggestions"][0]["attributes"][0]["value"] == "recycled"
    assert body["rejected"] == ["A: dropped junk"]



def test_health(tmp_path: Path) -> None:
    resp = _client(tmp_path).get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_cors_preflight_allows_next_dev_origin(tmp_path: Path) -> None:
    # The frontend (localhost:3000) must be able to POST /decision-runs.
    client = _client(tmp_path)
    resp = client.options(
        "/api/decision-runs",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code == 200
    assert "access-control-allow-origin" in resp.headers
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_preflight_allows_delete(tmp_path: Path) -> None:
    """Audit fix (2026-10-23): the 'Start fresh' button sends DELETE. With the
    method missing from the CORS allow-list the browser blocked the preflight
    whenever the frontend is a separate origin (localhost dev or Vercel+API)."""
    client = _client(tmp_path)
    resp = client.options(
        "/api/decision-runs",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "DELETE",
        },
    )
    assert resp.status_code == 200
    assert "DELETE" in resp.headers.get("access-control-allow-methods", "")


def test_cors_blocks_unlisted_origin(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.options(
        "/api/decision-runs",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    origin = resp.headers.get("access-control-allow-origin")
    assert origin != "https://evil.example"


def test_post_run_returns_ranking_report(tmp_path: Path) -> None:
    resp = _client(tmp_path).post("/api/decision-runs", json=_brief_dict())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] in ("COMPLETED", "COMPLETED_WITH_LIMITATIONS")
    assert body["report"]["fixture_mode"] is True
    assert body["report"]["winner"] in ("A", "C")
    assert {r["concept_id"] for r in body["report"]["ranks"]} == {"A", "B", "C"}


def test_post_run_rejects_two_concepts(tmp_path: Path) -> None:
    brief = _brief_dict()
    brief["concepts"] = brief["concepts"][:2]
    resp = _client(tmp_path).post("/api/decision-runs", json=brief)
    assert resp.status_code == 422


def test_post_run_returns_503_when_the_database_is_unreachable(
    tmp_path: Path, monkeypatch
) -> None:
    """Live failure (2026-10-21): a DNS blip made the last write fail with
    InvalidatePoolError and the user got a bare 500 with no idea what to do.
    The API must now say what happened (503) and never leak the DB URL."""
    from sqlalchemy.exc import OperationalError

    from app.services import persistence

    def _boom(engine):
        raise OperationalError(
            "connect", {}, Exception("failed to resolve host 'db.internal'")
        )

    monkeypatch.setattr(persistence, "_session", _boom)
    monkeypatch.setattr(persistence, "DB_RETRY_BACKOFF_SECONDS", (0.0, 0.0))
    resp = _client(tmp_path).post("/api/decision-runs", json=_brief_dict())
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "database was unreachable" in detail
    assert "db.internal" not in detail
    assert "postgresql" not in detail


def test_get_run_bundle_returns_503_when_the_database_is_unreachable(
    tmp_path: Path, monkeypatch
) -> None:
    from sqlalchemy.exc import InvalidatePoolError

    from app.services import persistence

    def _boom(engine):
        raise InvalidatePoolError("pool could not connect")

    monkeypatch.setattr(persistence, "_session", _boom)
    monkeypatch.setattr(persistence, "DB_RETRY_BACKOFF_SECONDS", (0.0, 0.0))
    resp = _client(tmp_path).get("/api/decision-runs/some-run-id")
    assert resp.status_code == 503
    assert "database was unreachable" in resp.json()["detail"]


def test_get_run_bundle_returns_503_when_the_pool_is_exhausted(
    tmp_path: Path, monkeypatch
) -> None:
    """Audit (2026-10-23): a QueuePool checkout timeout surfaced as a bare
    500 ASGI traceback. It is a busy-database condition: 503, not a crash."""
    from sqlalchemy.exc import TimeoutError

    from app.services import persistence

    def _boom(engine):
        raise TimeoutError("QueuePool limit of size 5 overflow 10 reached")

    monkeypatch.setattr(persistence, "_session", _boom)
    resp = _client(tmp_path).get("/api/decision-runs/some-run-id")
    assert resp.status_code == 503
    assert "database was unreachable" in resp.json()["detail"]


def test_get_run_bundle_and_unknown_id(tmp_path: Path) -> None:
    client = _client(tmp_path)
    run_id = client.post("/api/decision-runs", json=_brief_dict()).json()["run_id"]
    got = client.get(f"/api/decision-runs/{run_id}")
    assert got.status_code == 200
    assert got.json()["run"]["run_id"] == run_id
    assert len(got.json()["evidence"]) >= 3
    missing = client.get("/api/decision-runs/does-not-exist")
    assert missing.status_code == 404
