"""Persistence retry tests (2026-10-21 live-failure fix).

Live failure: a DNS blip on the tethering connection made SQLAlchemy's pool
fail to open a connection in the middle of a run. The write raised
InvalidatePoolError and the whole run (2.5 minutes of live Qloo + LLM work)
was lost. These tests pin the behaviour:

* transient connection failures are retried a bounded number of times with a
  backoff, and the write eventually succeeds;
* a row that is already there (the previous attempt committed but the
  acknowledgement was lost) is treated as success, never as a duplicate;
* failures that a retry cannot fix are raised immediately, not retried.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError

from app.services import persistence
from app.services.persistence import (
    add_critic_finding,
    add_evidence_records,
    add_score_snapshot,
    add_workflow_event,
    create_run,
    get_engine,
    get_run_bundle,
    init_db,
    update_run_state,
)


class _FakeSession:
    """Minimal session stand-in that fails a fixed number of times."""

    def __init__(self, failures: list[Exception]) -> None:
        self._failures = list(failures)
        self.added: list[object] = []

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        if self._failures:
            raise self._failures.pop(0)

    def get(self, cls: object, pk: str) -> None:
        return None

    def execute(self, *args: object, **kwargs: object) -> list:
        return []

    def query(self, *args: object, **kwargs: object) -> list:
        return []


def _patch_session(monkeypatch, failures: list[Exception]) -> list[float]:
    waits: list[float] = []
    monkeypatch.setattr(persistence.time, "sleep", waits.append)
    fake = _FakeSession(failures)
    monkeypatch.setattr(persistence, "_session", lambda engine: fake)
    return waits


def test_transient_pool_failure_is_retried_and_the_write_succeeds(monkeypatch) -> None:
    waits = _patch_session(
        monkeypatch,
        [persistence.InvalidatePoolError("pool could not connect")],
    )
    run_id = create_run(
        get_engine("sqlite:///:memory:"), {"brief": "x"}, "v0.1", "w0.1"
    )
    assert len(run_id) == 32
    assert waits == [2.0]


def test_operational_error_is_retried(monkeypatch) -> None:
    waits = _patch_session(
        monkeypatch,
        [
            OperationalError("connect", {}, Exception("failed to resolve host")),
            OperationalError("connect", {}, Exception("failed to resolve host")),
        ],
    )
    create_run(get_engine("sqlite:///:memory:"), {"brief": "x"}, "v0.1", "w0.1")
    assert waits == [2.0, 5.0]


def test_retry_gives_up_after_the_configured_attempts(monkeypatch) -> None:
    waits = _patch_session(
        monkeypatch,
        [OperationalError("connect", {}, Exception("down"))] * 5,
    )
    with pytest.raises(OperationalError):
        create_run(get_engine("sqlite:///:memory:"), {"brief": "x"}, "v0.1", "w0.1")
    assert len(waits) == persistence.DB_RETRY_ATTEMPTS - 1


def test_non_transient_failure_is_not_retried(monkeypatch) -> None:
    waits = _patch_session(monkeypatch, [ValueError("unknown run_id")])
    with pytest.raises(ValueError):
        update_run_state(get_engine("sqlite:///:memory:"), "nope", "SCORING")
    assert waits == []


def test_already_persisted_row_is_treated_as_success(monkeypatch) -> None:
    # The previous attempt committed but the acknowledgement was lost: the
    # insert now conflicts. The desired state is already true.
    waits = _patch_session(
        monkeypatch,
        [IntegrityError("INSERT", {}, Exception("duplicate key"))],
    )
    event_id = add_workflow_event(
        get_engine("sqlite:///:memory:"), "run-1", 1, "SCORING", "enter_scoring", {}
    )
    assert len(event_id) == 32
    assert waits == []


def test_interface_error_is_retried(monkeypatch) -> None:
    waits = _patch_session(
        monkeypatch, [InterfaceError("stmt", {}, Exception("connection dropped"))]
    )
    create_run(get_engine("sqlite:///:memory:"), {"brief": "x"}, "v0.1", "w0.1")
    assert waits == [2.0]


# --- real database: the writes stay idempotent under retry ------------------

def _engine():
    eng = get_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


def test_evidence_rows_are_not_duplicated_by_a_second_write() -> None:
    eng = _engine()
    run_id = create_run(eng, {"brief": "x"}, "v0.1", "w0.1")
    record = {"evidence_id": "e1", "source": "qloo", "qloo_entity_id": "urn:x"}
    add_evidence_records(eng, run_id, [record])
    add_evidence_records(eng, run_id, [record])  # retry / duplicate write
    bundle = get_run_bundle(eng, run_id)
    assert len(bundle["evidence"]) == 1


def test_workflow_events_are_not_duplicated_by_a_second_write() -> None:
    eng = _engine()
    run_id = create_run(eng, {"brief": "x"}, "v0.1", "w0.1")
    add_workflow_event(eng, run_id, 1, "SCORING", "enter_scoring", {})
    add_workflow_event(eng, run_id, 1, "SCORING", "enter_scoring", {})
    bundle = get_run_bundle(eng, run_id)
    assert len(bundle["events"]) == 1


def test_score_snapshots_are_not_duplicated_by_a_second_write() -> None:
    eng = _engine()
    run_id = create_run(eng, {"brief": "x"}, "v0.1", "w0.1")
    add_score_snapshot(eng, run_id, "A", {"rank": 1}, "v0.1")
    add_score_snapshot(eng, run_id, "A", {"rank": 1}, "v0.1")
    bundle = get_run_bundle(eng, run_id)
    assert len(bundle["scores"]) == 1


def test_critic_findings_are_not_duplicated_by_a_second_write() -> None:
    eng = _engine()
    run_id = create_run(eng, {"brief": "x"}, "v0.1", "w0.1")
    finding = {"issue_code": "CAUSAL_OVERCLAIM", "severity": "minor"}
    add_critic_finding(eng, run_id, finding, ordinal=0)
    add_critic_finding(eng, run_id, finding, ordinal=0)
    bundle = get_run_bundle(eng, run_id)
    assert len(bundle["critic"]) == 1


def test_distinct_critic_findings_are_all_kept() -> None:
    eng = _engine()
    run_id = create_run(eng, {"brief": "x"}, "v0.1", "w0.1")
    add_critic_finding(eng, run_id, {"issue_code": "A", "severity": "minor"}, ordinal=0)
    add_critic_finding(eng, run_id, {"issue_code": "B", "severity": "minor"}, ordinal=1)
    bundle = get_run_bundle(eng, run_id)
    assert len(bundle["critic"]) == 2
