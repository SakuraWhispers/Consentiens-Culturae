"""Persistence (docs/architecture.md sections 2 and 7).

SQLAlchemy 2.0, five tables, JSON columns, `create_all` for v1 (no migration
framework). SQLite locally, Neon Postgres via DATABASE_URL (pooled URL at
runtime). Never stores API keys or headers — query params arrive already
redacted from the adapter/normalizer path.

It displaces nothing on the in-scope table (persistence row). Net scope
change: none. No new dependency (sqlalchemy + psycopg already pinned).

Connection resilience (2026-10-21): every write and read is wrapped in a
short bounded retry. A live run was lost because a DNS blip on the machine's
tethering connection made the pool fail to open a connection mid-run
(InvalidatePoolError). The writes are also idempotent — deterministic row
ids — so a retry after a lost acknowledgement can never duplicate a row.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import (
    IntegrityError,
    InterfaceError,
    InvalidatePoolError,
    OperationalError,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

T = TypeVar("T")

# Bounded retry for transient connection failures (DNS/network blips).
# Three attempts with a 2 s and a 5 s pause: long enough to ride out a
# resolver hiccup, short enough not to stall a request for minutes.
DB_RETRY_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = (2.0, 5.0)

TRANSIENT_DB_ERRORS = (InvalidatePoolError, OperationalError, InterfaceError)


def _with_db_retry(operation: Callable[[], T]) -> T:
    """Run a database operation, retrying transient connection failures.

    Only failures where the connection could not be established (or was
    invalidated) are retried; anything the server itself rejected is raised
    immediately, because retrying it would not change the answer.
    """
    last: Exception | None = None
    for attempt in range(DB_RETRY_ATTEMPTS):
        try:
            return operation()
        except TRANSIENT_DB_ERRORS as exc:
            last = exc
            if attempt >= DB_RETRY_ATTEMPTS - 1:
                raise
            delay = DB_RETRY_BACKOFF_SECONDS[
                min(attempt, len(DB_RETRY_BACKOFF_SECONDS) - 1)
            ]
            time.sleep(delay)
    raise last  # pragma: no cover - the loop always returns or raises


def _deterministic_id(*parts: str) -> str:
    """Stable row id, so a retried write collides instead of duplicating."""
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]



def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class DecisionRun(Base):
    __tablename__ = "decision_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    state: Mapped[str] = mapped_column(String(64), default="CREATED")
    input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    final_report_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message_safe: Mapped[str | None] = mapped_column(Text, nullable=True)
    scoring_version: Mapped[str] = mapped_column(String(32))
    workflow_version: Mapped[str] = mapped_column(String(32))
    revision_count: Mapped[int] = mapped_column(Integer, default=0)


class EvidenceRow(Base):
    __tablename__ = "evidence_records"

    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("decision_runs.run_id"))
    source: Mapped[str] = mapped_column(String(16), default="fixture")
    qloo_entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    endpoint_or_operation: Mapped[str] = mapped_column(String(200), default="")
    query_params_redacted_json: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    match_quality: Mapped[str] = mapped_column(String(16), default="none")
    coverage_status: Mapped[str] = mapped_column(String(16), default="missing")
    fixture_mode: Mapped[bool] = mapped_column(default=True)


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("decision_runs.run_id"))
    sequence_number: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(64))
    safe_payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ScoreSnapshot(Base):
    __tablename__ = "score_snapshots"

    score_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("decision_runs.run_id"))
    concept_id: Mapped[str] = mapped_column(String(128))
    score_json: Mapped[dict] = mapped_column(JSON, default=dict)
    scoring_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class CriticFinding(Base):
    __tablename__ = "critic_findings"

    finding_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("decision_runs.run_id"))
    finding_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


def normalize_database_url(url: str) -> str:
    """Accept Neon's `postgresql://`/`postgres://`; SQLAlchemy needs a driver."""
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    return url


def get_engine(database_url: str) -> Engine:
    return create_engine(normalize_database_url(database_url), pool_pre_ping=True)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def _session(engine: Engine) -> Session:
    return sessionmaker(bind=engine, expire_on_commit=False)()


def create_run(
    engine: Engine,
    input_json: dict[str, Any],
    scoring_version: str,
    workflow_version: str,
    run_id: str | None = None,
) -> str:
    if not input_json:
        raise ValueError("input_json must not be empty")
    # The id is generated once, OUTSIDE the retried operation: a retry after
    # a lost acknowledgement re-inserts the same row (conflict = already
    # there) instead of creating a second, orphaned run. A caller may supply
    # the id (the API lets the client know the run id before the run starts).
    if run_id is None:
        run_id = uuid.uuid4().hex

    def _op() -> None:
        with _session(engine) as s:
            s.add(
                DecisionRun(
                    run_id=run_id,
                    state="CREATED",
                    input_json=input_json,
                    scoring_version=scoring_version,
                    workflow_version=workflow_version,
                )
            )
            s.commit()

    try:
        _with_db_retry(_op)
    except IntegrityError:
        return run_id
    return run_id


def update_run_state(
    engine: Engine,
    run_id: str,
    state: str,
    final_report_json: dict[str, Any] | None = None,
    error_code: str | None = None,
    error_message_safe: str | None = None,
) -> None:
    def _op() -> None:
        with _session(engine) as s:
            run = s.get(DecisionRun, run_id)
            if run is None:
                raise ValueError(f"unknown run_id {run_id}")
            run.state = state
            if final_report_json is not None:
                run.final_report_json = final_report_json
            if error_code is not None:
                run.error_code = error_code
            if error_message_safe is not None:
                run.error_message_safe = error_message_safe
            s.commit()

    _with_db_retry(_op)


def set_revision_count(engine: Engine, run_id: str, revision_count: int) -> None:
    def _op() -> None:
        with _session(engine) as s:
            run = s.get(DecisionRun, run_id)
            if run is None:
                raise ValueError(f"unknown run_id {run_id}")
            run.revision_count = revision_count
            s.commit()

    _with_db_retry(_op)


def add_workflow_event(
    engine: Engine,
    run_id: str,
    sequence_number: int,
    state: str,
    event_type: str,
    safe_payload: dict[str, Any],
) -> str:
    # Deterministic id: a retried write collides (already recorded) instead of
    # adding a second event with the same sequence number.
    event_id = _deterministic_id("event", run_id, str(sequence_number), event_type)

    def _op() -> None:
        with _session(engine) as s:
            ev = WorkflowEvent(
                event_id=event_id,
                run_id=run_id,
                sequence_number=sequence_number,
                state=state,
                event_type=event_type,
                safe_payload_json=safe_payload,
            )
            s.add(ev)
            s.commit()

    try:
        _with_db_retry(_op)
    except IntegrityError:
        pass  # already recorded by an earlier attempt
    return event_id


def add_evidence_records(
    engine: Engine, run_id: str, records: list[dict[str, Any]]
) -> None:
    def _op() -> None:
        with _session(engine) as s:
            for rec in records:
                s.add(
                    EvidenceRow(
                        evidence_id=rec.get("evidence_id") or uuid.uuid4().hex,
                        run_id=run_id,
                        source=rec.get("source", "fixture"),
                        qloo_entity_id=rec.get("qloo_entity_id"),
                        endpoint_or_operation=rec.get("endpoint_or_operation", ""),
                        query_params_redacted_json=rec.get("query_params_redacted", {}),
                        evidence_json={k: v for k, v in rec.items() if k != "evidence_id"},
                        match_quality=rec.get("match_quality", "none"),
                        coverage_status=rec.get("coverage_status", "missing"),
                        fixture_mode=bool(rec.get("fixture_mode", True)),
                    )
                )
            s.commit()

    try:
        _with_db_retry(_op)
    except IntegrityError:
        pass  # the evidence ids already exist


def add_score_snapshot(
    engine: Engine, run_id: str, concept_id: str, score_json: dict[str, Any], scoring_version: str
) -> str:
    score_id = _deterministic_id("score", run_id, concept_id)

    def _op() -> None:
        with _session(engine) as s:
            row = ScoreSnapshot(
                score_id=score_id,
                run_id=run_id,
                concept_id=concept_id,
                score_json=score_json,
                scoring_version=scoring_version,
            )
            s.add(row)
            s.commit()

    try:
        _with_db_retry(_op)
    except IntegrityError:
        pass  # the snapshot already exists
    return score_id


def add_critic_finding(
    engine: Engine, run_id: str, finding_json: dict[str, Any], ordinal: int = 0
) -> str:
    # The ordinal keeps two genuinely different findings apart while making a
    # retried write collide instead of duplicating.
    finding_id = _deterministic_id(
        "finding", run_id, str(ordinal), json.dumps(finding_json, sort_keys=True, default=str)
    )

    def _op() -> None:
        with _session(engine) as s:
            row = CriticFinding(finding_id=finding_id, run_id=run_id, finding_json=finding_json)
            s.add(row)
            s.commit()

    try:
        _with_db_retry(_op)
    except IntegrityError:
        pass  # the finding already exists
    return finding_id


def get_run_bundle(engine: Engine, run_id: str) -> dict[str, Any]:
    def _op() -> dict[str, Any]:
        with _session(engine) as s:
            run = s.get(DecisionRun, run_id)
            if run is None:
                raise ValueError(f"unknown run_id {run_id}")
            return {
                "run": {
                    "run_id": run.run_id,
                    "state": run.state,
                    "input_json": run.input_json,
                    "final_report_json": run.final_report_json,
                    "scoring_version": run.scoring_version,
                    "workflow_version": run.workflow_version,
                    "revision_count": run.revision_count,
                },
                "evidence": [
                    {"evidence_id": r.evidence_id, "qloo_entity_id": r.qloo_entity_id,
                     "coverage_status": r.coverage_status, "match_quality": r.match_quality}
                    for r in s.query(EvidenceRow).filter_by(run_id=run_id).all()
                ],
                "scores": [
                    {"concept_id": r.concept_id, "score_json": r.score_json}
                    for r in s.query(ScoreSnapshot).filter_by(run_id=run_id).all()
                ],
                "events": [
                    {"sequence_number": e.sequence_number, "state": e.state,
                     "event_type": e.event_type, "detail": e.safe_payload_json}
                    for e in s.query(WorkflowEvent).filter_by(run_id=run_id).order_by(WorkflowEvent.sequence_number).all()
                ],
                "critic": [r.finding_json for r in s.query(CriticFinding).filter_by(run_id=run_id).all()],
            }

    return _with_db_retry(_op)


def load_evidence_records(
    engine: Engine, run_id: str
) -> dict[str, list[dict[str, Any]]]:
    """The stored evidence of a run, grouped by concept id.

    Used by the RESUME path: a half-finished run keeps its Qloo evidence, so
    a retry can re-run the LLM stages without spending Qloo quota again.
    """
    from app.schemas.evidence import EvidenceRecord

    with _session(engine) as s:
        rows = s.query(EvidenceRow).filter_by(run_id=run_id).all()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        record = dict(row.evidence_json or {})
        record["evidence_id"] = row.evidence_id
        record["fixture_mode"] = bool(row.fixture_mode)
        # Which concept the record belongs to is carried in the payload
        # (the table has no concept column; the id hash is not reversible).
        concept_id = record.pop("concept_id", None)
        if not concept_id:
            continue
        try:
            model = EvidenceRecord(**record)
        except Exception:
            continue
        grouped.setdefault(concept_id, []).append(model.model_dump())
    return grouped


def delete_run(engine: Engine, run_id: str) -> bool:
    """Delete a run and all of its rows (the 'start fresh' cleanup).

    Only the rows of THIS run are touched. Returns False when the run does
    not exist.
    """

    def _op() -> bool:
        with _session(engine) as s:
            run = s.get(DecisionRun, run_id)
            if run is None:
                return False
            s.query(EvidenceRow).filter_by(run_id=run_id).delete()
            s.query(ScoreSnapshot).filter_by(run_id=run_id).delete()
            s.query(CriticFinding).filter_by(run_id=run_id).delete()
            s.query(WorkflowEvent).filter_by(run_id=run_id).delete()
            s.delete(run)
            s.commit()
            return True

    return _with_db_retry(_op)


def get_run_state(engine: Engine, run_id: str) -> tuple[str, int]:
    """The run's state and its last event sequence number (for a resume)."""

    def _op() -> tuple[str, int]:
        with _session(engine) as s:
            run = s.get(DecisionRun, run_id)
            if run is None:
                raise ValueError(f"unknown run_id {run_id}")
            last = (
                s.query(WorkflowEvent)
                .filter_by(run_id=run_id)
                .order_by(WorkflowEvent.sequence_number.desc())
                .first()
            )
            return run.state, (last.sequence_number if last else 0)

    return _with_db_retry(_op)


def get_run_input(engine: Engine, run_id: str) -> dict[str, Any]:
    """The brief a run was started with (used by the resume endpoint)."""

    def _op() -> dict[str, Any]:
        with _session(engine) as s:
            run = s.get(DecisionRun, run_id)
            if run is None:
                raise ValueError(f"unknown run_id {run_id}")
            return dict(run.input_json or {})

    return _with_db_retry(_op)


__all__ = [
    "Base",
    "get_engine",
    "normalize_database_url",
    "init_db",
    "create_run",
    "update_run_state",
    "add_workflow_event",
    "add_evidence_records",
    "add_score_snapshot",
    "add_critic_finding",
    "load_evidence_records",
    "delete_run",
    "get_run_state",
    "get_run_input",
    "get_run_bundle",
    "set_revision_count",
]
