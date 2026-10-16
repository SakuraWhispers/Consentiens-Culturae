"""Normalized evidence records (docs/architecture.md section 2, section 7).

Built exactly from what Qloo DOCS-VERIFIED responses contain (see
docs/qloo-api-notes.md section 3). Unknown optional fields are IGNORED, not
invented; where a documented field is expected but absent, the record is
`partial` with the field name in `limitations` (hard rule 1: never fabricate).
"""

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4
import hashlib

from pydantic import BaseModel, Field, field_validator

# The only source types; `qloo` implies a live call, `fixture` implies
# hand-written or recorded input and MUST set fixture_mode=True.
SourceKind = Literal["qloo", "fixture"]

CoverageStatus = Literal["available", "partial", "missing", "error", "ambiguous"]

MatchQuality = Literal["exact", "partial", "ambiguous", "none"]

# Doc-sourced error codes valid on coverage_status="error" rows
# (docs/qloo-api-notes.md section 5).
ErrorCode = Literal[
    "QLOO_AUTH_FAILED",
    "QLOO_RATE_LIMITED",
    "QLOO_UPSTREAM_ERROR",
    "QLOO_TIMEOUT",
    "QLOO_MALFORMED_RESPONSE",
    "QLOO_NO_MATCH",
    "QLOO_FIELD_UNEXPECTED",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def stable_evidence_id(
    endpoint_or_operation: str,
    query_params_redacted: dict,
    qloo_entity_id: str | None,
) -> str:
    """Deterministic id for reproducibility: same inputs -> same id.

    Uses only redacted params; never the API key or any header value.
    """
    material = f"{endpoint_or_operation}|{sorted(query_params_redacted.items())}|{qloo_entity_id}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


class EvidenceRecord(BaseModel):
    """One normalized piece of Qloo evidence, with provenance."""

    evidence_id: str = Field(min_length=8, max_length=64)
    source: SourceKind
    fixture_mode: bool = Field(
        description="True whenever this record did not come from a live Qloo call."
    )
    endpoint_or_operation: str = Field(min_length=1, max_length=200)
    query_params_redacted: dict[str, str] = Field(default_factory=dict)
    # Qloo identity. entity fields may be absent (no match / error rows).
    qloo_entity_id: str | None = None
    entity_name: str | None = Field(default=None, max_length=300)
    entity_subtype: str | None = Field(default=None, max_length=100)
    # Normalized values extracted from the documented response shape.
    popularity: float | None = Field(default=None, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list, description="list of tag URN ids")
    # Provenance and status.
    retrieved_at: datetime = Field(default_factory=_utcnow)
    match_quality: MatchQuality = "exact"
    coverage_status: CoverageStatus = "available"
    error_code: ErrorCode | None = None
    limitations: list[str] = Field(default_factory=list)
    # The raw record as parsed from the source, AFTER redaction; reproducibility
    # keeps only what is documented in docs/qloo-api-notes.md section 6.
    raw: dict = Field(default_factory=dict)

    @field_validator("retrieved_at")
    @classmethod
    def _require_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("retrieved_at must carry a timezone")
        return v


def make_error_record(
    endpoint_or_operation: str,
    query_params_redacted: dict[str, str],
    error_code: ErrorCode,
    source: SourceKind,
    fixture_mode: bool,
    limitations: list[str] | None = None,
) -> EvidenceRecord:
    """One failure = one record, never silent and never a low score.

    Missing/empty evidence becomes `missing` (QLOO_NO_MATCH), errors become
    `error` with the code (docs/qloo-api-notes.md section 5).
    """
    status: CoverageStatus = "missing" if error_code == "QLOO_NO_MATCH" else "error"
    if error_code == "QLOO_NO_MATCH":
        limitations = list(limitations or [])
        limitations.append("documented empty results.entities: no match, not a negative signal")
    return EvidenceRecord(
        evidence_id=stable_evidence_id(endpoint_or_operation, query_params_redacted, None),
        source=source,
        fixture_mode=fixture_mode,
        endpoint_or_operation=endpoint_or_operation,
        query_params_redacted=query_params_redacted,
        match_quality="none",
        coverage_status=status,
        error_code=error_code,
        limitations=limitations or [],
        raw={},
    )


__all__ = [
    "EvidenceRecord",
    "CoverageStatus",
    "MatchQuality",
    "SourceKind",
    "ErrorCode",
    "stable_evidence_id",
    "make_error_record",
    "uuid4",
]
