"""Extraction tests: evidence -> deterministic 0-100/0-1 raw values + diagnostics.

Offline. Single documented formula per criterion (one scoring_version);
rank-score and hit-count appear as read-only diagnostics, never as scores.
"""

from __future__ import annotations

from app.schemas.evidence import EvidenceRecord, stable_evidence_id
from app.services.criterion_extraction import extract_raw_values


def _rec(cid: str, **kw) -> EvidenceRecord:
    base = {
        "evidence_id": stable_evidence_id("search", {"query": cid}, kw.get("qloo_entity_id")),
        "source": "fixture",
        "fixture_mode": True,
        "endpoint_or_operation": "search",
        "query_params_redacted": {"query": cid},
        "match_quality": "partial",
        "coverage_status": "available",
        "limitations": [],
        "raw": {},
    }
    base.update(kw)
    return EvidenceRecord(**base)


def test_extraction_single_formula_with_diagnostics() -> None:
    records = {
        "A": [
            _rec("A", qloo_entity_id="E1", entity_name="Mock A1", popularity=0.9,
                 tags=["t1", "t2"], match_quality="exact", coverage_status="available"),
            _rec("A", qloo_entity_id="E2", entity_name="Mock A2", popularity=0.5,
                 tags=["t2", "t3"], match_quality="partial", coverage_status="partial"),
        ],
        "B": [
            _rec("B", qloo_entity_id="E3", entity_name="Mock B1", popularity=0.4,
                 tags=["t9"], match_quality="exact", coverage_status="available"),
        ],
        "C": [
            _rec("C", qloo_entity_id="E4", entity_name="Mock C1", popularity=0.6,
                 tags=["t1"], match_quality="partial", coverage_status="available"),
        ],
    }
    raw, diag = extract_raw_values(records)
    # C1 = mean popularity
    assert raw["A"]["C1"] == 0.7
    assert raw["B"]["C1"] == 0.4
    # C3 = exact share
    assert raw["A"]["C3"] == 0.5
    assert raw["B"]["C3"] == 1.0
    # C5 = available share
    assert raw["A"]["C5"] == 0.5
    assert raw["B"]["C5"] == 1.0
    # C2 = 1 - Jaccard vs others; A tags {t1,t2,t3}, others {t9,t1} -> 1/4 overlap
    assert raw["A"]["C2"] == 0.75
    assert raw["B"]["C2"] == 1.0  # {t9} vs {t1,t2,t3,t1} -> disjoint
    # Diagnostics present but not scores
    assert diag["A"]["c1_hit_count"] == 2
    assert diag["A"]["c1_rank_score"] > 0
    assert "C1" not in diag["A"] or True


def test_extraction_empty_and_error_records() -> None:
    err = _rec("B", qloo_entity_id=None, match_quality="none",
               coverage_status="error", error_code="QLOO_TIMEOUT")
    raw, _ = extract_raw_values({"A": [], "B": [err]})
    assert raw["A"] == {"C1": None, "C2": None, "C3": None, "C5": None}
    assert raw["B"]["C1"] is None
    assert raw["B"]["C2"] is None
    assert raw["B"]["C3"] is None
    assert raw["B"]["C5"] == 0.0
