"""Persistence tests: SQLite in-memory/file, offline (G2).

Neon is verified separately via a safe connectivity probe (server version
only, never the URL). These tests must run with no network and no secrets.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from app.services.persistence import (
    add_critic_finding,
    add_evidence_records,
    add_score_snapshot,
    add_workflow_event,
    create_run,
    delete_run,
    get_engine,
    get_run_bundle,
    init_db,
    update_run_state,
)


@pytest.fixture()
def engine():
    eng = get_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


def test_get_engine_accepts_both_postgres_prefixes_without_connecting() -> None:
    for url in ("postgresql://u:p@host/db", "postgresql+psycopg://u:p@host/db"):
        eng = get_engine(url)
        assert "postgres" in eng.url.drivername


def test_the_bundle_cache_serves_reads_until_a_write_evicts(engine) -> None:
    """Pool-storm fix (2026-10-24): repeated result-page polls re-mount five
    tables per tick. The cached bundle satisfies a poll until ANY write to
    this run's rows evicts it - then the read must reflect the new state."""
    run_id = create_run(
        engine,
        input_json={"brief": "b", "concepts": ["a"]},
        scoring_version="v0.1",
        workflow_version="w0.1",
    )
    first = get_run_bundle(engine, run_id)
    second = get_run_bundle(engine, run_id)
    assert second == first, "an unchanged run must be served from the cache"

    update_run_state(engine, run_id, "SCORING")
    after_state = get_run_bundle(engine, run_id)
    assert after_state["run"]["state"] == "SCORING", "a write must evict"

    add_evidence_records(
        engine, run_id, [{"evidence_id": "row-1", "concept_id": "a"}]
    )
    after_write = get_run_bundle(engine, run_id)
    assert len(after_write["evidence"]) == 1, "a write must evict"

    delete_run(engine, run_id)  # also: the delete path itself invalidates
    with pytest.raises(ValueError, match="unknown run_id"):
        get_run_bundle(engine, run_id)


def test_pool_pressure_is_logged_when_the_pool_overflows(tmp_path, caplog) -> None:
    """Audit (2026-10-23): a QueuePool timeout used to be undiscoverable
    after the fact. The checkout hook names the pressure in the log."""
    eng = get_engine(f"sqlite:///{tmp_path}/pool.db")
    held = [eng.connect() for _ in range(6)]  # 5 pooled + 1 overflow
    try:
        assert any("db pool pressure" in r.message for r in caplog.records)
    finally:
        for conn in held:
            conn.close()


def test_run_lifecycle_roundtrip(engine) -> None:
    run_id = create_run(
        engine,
        input_json={"brief": "mock", "concepts": ["a", "b", "c"]},
        scoring_version="v0.1",
        workflow_version="w0.1",
    )
    add_workflow_event(engine, run_id, 1, "CREATED", "run_created", {})
    add_evidence_records(
        engine,
        run_id,
        [{"qloo_entity_id": "E1", "entity_name": "Mock", "coverage_status": "available"}],
    )
    add_score_snapshot(
        engine, run_id, "c1", {"concept_id": "c1", "status": "RANKED", "weighted_total": 61.5}, "v0.1"
    )
    update_run_state(engine, run_id, "COMPLETED", final_report_json={"winner": "c1"})
    add_critic_finding(engine, run_id, {"issue_code": "NONE", "severity": "info"})

    bundle = get_run_bundle(engine, run_id)
    assert bundle["run"]["state"] == "COMPLETED"
    assert bundle["run"]["final_report_json"] == {"winner": "c1"}
    assert len(bundle["evidence"]) == 1
    assert bundle["evidence"][0]["qloo_entity_id"] == "E1"
    assert len(bundle["scores"]) == 1
    assert len(bundle["events"]) == 1
    assert len(bundle["critic"]) == 1


def test_create_run_rejects_empty_input(engine) -> None:
    with pytest.raises(ValueError):
        create_run(engine, input_json={}, scoring_version="v0.1", workflow_version="w0.1")


def test_create_run_refuses_a_foreign_brief_on_the_same_run_id(engine) -> None:
    """Audit fix (2026-10-23): an existing run_id reused with a DIFFERENT brief
    would mix two runs' evidence and overwrite the report - refused. The
    identical brief stays an idempotent retry (row reused, no error)."""
    input_a: dict[str, object] = {"brief": "mock-a"}
    input_b: dict[str, object] = {"brief": "mock-b"}
    first = create_run(
        engine, input_json=input_a, scoring_version="v0.1", workflow_version="w0.1"
    )
    assert (
        create_run(
            engine,
            input_json=input_a,
            scoring_version="v0.1",
            workflow_version="w0.1",
            run_id=first,
        )
        == first
    ), "the same brief reusing its id is a retry, not a refusal"
    with pytest.raises(ValueError, match="different brief"):
        create_run(
            engine,
            input_json=input_b,
            scoring_version="v0.1",
            workflow_version="w0.1",
            run_id=first,
        )
