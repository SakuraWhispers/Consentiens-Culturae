"""API tests (Level B): health, run creation, validation, retrieval. Offline."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

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


def test_get_run_bundle_and_unknown_id(tmp_path: Path) -> None:
    client = _client(tmp_path)
    run_id = client.post("/api/decision-runs", json=_brief_dict()).json()["run_id"]
    got = client.get(f"/api/decision-runs/{run_id}")
    assert got.status_code == 200
    assert got.json()["run"]["run_id"] == run_id
    assert len(got.json()["evidence"]) >= 3
    missing = client.get("/api/decision-runs/does-not-exist")
    assert missing.status_code == 404
