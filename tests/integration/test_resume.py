"""Resume and start-fresh tests (2026-10-22).

A half-finished run (the process died, or the database blipped) leaves rows
behind. The user chooses what a retry does:

* RESUME: continue the SAME run, reusing the Qloo evidence it already
  stored — no Qloo call is repeated, so a retry costs no Qloo quota;
* START FRESH: delete the partial rows and run again from nothing, so the
  database does not accumulate half-rows.

Both are exercised here through the API.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.rate_limiter import reset_run_limiter
from app.services.persistence import get_run_bundle

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(autouse=True)
def _no_run_gap():
    # These tests make several runs in a row; the 30s start-gap and the
    # daily cap of the limiter would turn them into 429s.
    saved = {
        k: os.environ.get(k)
        for k in ("RUN_MIN_GAP_SECONDS", "RUNS_PER_DAY")
    }
    os.environ["RUN_MIN_GAP_SECONDS"] = "0"
    os.environ["RUNS_PER_DAY"] = "0"
    reset_run_limiter()
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    reset_run_limiter()


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        database_url=f"sqlite:///{tmp_path}/resume_test.db",
        app_mode="fixture",
        fixtures_dir=FIXTURES_DIR,
    )
    return TestClient(app)


def _brief_dict() -> dict:
    return {
        "market": "US, online and indie bookstores",
        "audience_description": "Design-conscious note-takers aged 18-35",
        "business_goal": "Pick one of three concepts for a limited holiday run",
        "constraints": [],
        "weights": {"c1": 0.35, "c2": 0.20, "c3": 0.25, "c5": 0.20},
        "concepts": [
            {
                "concept_id": "A",
                "name": "Mock Studio Notebooks",
                "description": "Recycled notebook",
                "attributes": {"material": "recycled"},
            },
            {
                "concept_id": "B",
                "name": "Mock Luxury Pen",
                "description": "Over-budget pen",
                "attributes": {"material": "virgin-plastic"},
            },
            {
                "concept_id": "C",
                "name": "Mock Desk Organizer",
                "description": "Fiber organizer",
                "attributes": {"material": "recycled"},
            },
        ],
    }


def test_client_supplied_run_id_is_used_and_visible(tmp_path: Path) -> None:
    reset_run_limiter()
    client = _client(tmp_path)
    run_id = "a" * 32
    resp = client.post("/api/decision-runs", json={**_brief_dict(), "run_id": run_id})
    assert resp.status_code == 200, resp.text
    assert resp.json()["run_id"] == run_id
    got = client.get(f"/api/decision-runs/{run_id}")
    assert got.status_code == 200
    assert got.json()["run"]["run_id"] == run_id


def test_a_malformed_client_run_id_is_rejected(tmp_path: Path) -> None:
    reset_run_limiter()
    client = _client(tmp_path)
    resp = client.post("/api/decision-runs", json={**_brief_dict(), "run_id": "not-hex"})
    assert resp.status_code == 422


def test_resume_reuses_the_stored_evidence_and_finishes_the_run(tmp_path: Path) -> None:
    reset_run_limiter()
    client = _client(tmp_path)
    run_id = "b" * 32
    first = client.post("/api/decision-runs", json={**_brief_dict(), "run_id": run_id})
    assert first.status_code == 200
    bundle = client.get(f"/api/decision-runs/{run_id}").json()
    assert bundle["run"]["state"] in ("COMPLETED", "COMPLETED_WITH_LIMITATIONS")
    evidence_before = len(bundle["evidence"])

    # Simulate an interrupted run: the state stays non-terminal.
    from app.services.persistence import get_engine, update_run_state

    engine = get_engine(f"sqlite:///{tmp_path}/resume_test.db")
    update_run_state(engine, run_id, "CRITIC_REVIEW")

    resumed = client.post(f"/api/decision-runs/{run_id}/resume")
    assert resumed.status_code == 200, resumed.text
    body = resumed.json()
    assert body["run_id"] == run_id
    assert body["state"] in ("COMPLETED", "COMPLETED_WITH_LIMITATIONS")
    # The evidence was reused, not re-fetched: same count, and the report
    # says the run was resumed.
    assert any("resumed run" in lim for lim in body["report"]["limitations"])
    bundle_after = client.get(f"/api/decision-runs/{run_id}").json()
    assert len(bundle_after["evidence"]) == evidence_before


def test_resuming_a_finished_run_is_refused(tmp_path: Path) -> None:
    reset_run_limiter()
    client = _client(tmp_path)
    run_id = "c" * 32
    client.post("/api/decision-runs", json={**_brief_dict(), "run_id": run_id})
    resp = client.post(f"/api/decision-runs/{run_id}/resume")
    assert resp.status_code == 409
    assert "nothing to resume" in resp.json()["detail"]


def test_resuming_an_unknown_run_is_a_404(tmp_path: Path) -> None:
    reset_run_limiter()
    client = _client(tmp_path)
    resp = client.post("/api/decision-runs/deadbeef/resume")
    assert resp.status_code == 404


def test_start_fresh_deletes_the_partial_rows(tmp_path: Path) -> None:
    reset_run_limiter()
    client = _client(tmp_path)
    run_id = "d" * 32
    client.post("/api/decision-runs", json={**_brief_dict(), "run_id": run_id})
    assert client.get(f"/api/decision-runs/{run_id}").status_code == 200

    deleted = client.delete(f"/api/decision-runs/{run_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    # The run and all of its rows are gone (database hygiene).
    assert client.get(f"/api/decision-runs/{run_id}").status_code == 404


def test_deleting_an_unknown_run_is_a_404(tmp_path: Path) -> None:
    reset_run_limiter()
    client = _client(tmp_path)
    assert client.delete("/api/decision-runs/nope").status_code == 404


def test_the_resume_path_keeps_the_event_history(tmp_path: Path) -> None:
    reset_run_limiter()
    client = _client(tmp_path)
    run_id = "e" * 32
    client.post("/api/decision-runs", json={**_brief_dict(), "run_id": run_id})

    from app.services.persistence import get_engine, update_run_state

    engine = get_engine(f"sqlite:///{tmp_path}/resume_test.db")
    update_run_state(engine, run_id, "CRITIC_REVIEW")
    client.post(f"/api/decision-runs/{run_id}/resume")

    bundle = get_run_bundle(engine, run_id)
    types = [e["event_type"] for e in bundle["events"]]
    assert "enter_failed_retryable" in types
    assert types.count("enter_retrieving_evidence") == 2
