"""Coordinator tests: fixture-mode run path end-to-end + reproducibility (G2).

Offline (FixtureSource + SQLite memory). Live confirmation runs separately.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.integrations.qloo_adapter import FixtureSource
from app.schemas.brief import DecisionBrief
from app.services.persistence import get_engine, get_run_bundle, init_db
from app.workflow.coordinator import run_decision

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"

SCORING_VERSION = "v0.1-g2"


def _brief() -> DecisionBrief:
    return DecisionBrief(
        market="US, online and indie bookstores",
        audience_description="Design-conscious note-takers aged 18-35, buying for self and gifting",
        business_goal="Pick one of three concepts for a limited holiday run",
        constraints=[
            {"attribute": "material", "value": "recycled"},
            {"attribute": "price_band", "value": "under-25"},
            {"attribute": "product_type", "value": "stationery"},
        ],
        weights={"c1": 0.35, "c2": 0.20, "c3": 0.25, "c5": 0.20},
        concepts=[
            {
                "concept_id": "A",
                "name": "Mock Studio Notebooks",
                "description": "Recycled hardcover dot-grid notebook",
                "attributes": {"material": "recycled", "price_band": "under-25", "product_type": "stationery"},
            },
            {
                "concept_id": "B",
                "name": "Mock Luxury Pen",
                "description": "Virgin-plastic luxury pen over budget",
                "attributes": {"material": "virgin-plastic", "price_band": "over-100", "product_type": "stationery"},
            },
            {
                "concept_id": "C",
                "name": "Mock Desk Organizer",
                "description": "Molded-fiber desktop organizer",
                "attributes": {"material": "recycled", "price_band": "under-25", "product_type": "stationery"},
            },
        ],
    )


def _engine():
    eng = get_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


def test_fixture_run_completes_with_ranks_and_report() -> None:
    eng = _engine()
    out = run_decision(eng, _brief(), FixtureSource(FIXTURES_DIR), scoring_version=SCORING_VERSION)
    assert out["state"] in ("COMPLETED", "COMPLETED_WITH_LIMITATIONS")
    ranks = {r["concept_id"]: r for r in out["report"]["ranks"]}
    assert set(ranks) == {"A", "B", "C"}
    assert ranks["B"]["status"] == "INFEASIBLE"
    assert ranks["B"]["rank"] is None
    assert out["report"]["fixture_mode"] is True
    assert out["report"]["winner"] in ("A", "C")
    assert "Not a demand forecast" in out["report"]["disclaimer"]

    bundle = get_run_bundle(eng, out["run_id"])
    assert len(bundle["evidence"]) >= 3
    assert len(bundle["scores"]) == 3
    assert len(bundle["events"]) >= 8


def test_reproducibility_ten_runs_same_output() -> None:
    eng = _engine()
    src = FixtureSource(FIXTURES_DIR)
    first = run_decision(eng, _brief(), src, scoring_version=SCORING_VERSION)
    pertama = [(r["concept_id"], r["rank"], r["weighted_total"]) for r in first["report"]["ranks"]]
    for _ in range(9):
        out = run_decision(eng, _brief(), src, scoring_version=SCORING_VERSION)
        assert [(r["concept_id"], r["rank"], r["weighted_total"]) for r in out["report"]["ranks"]] == pertama
