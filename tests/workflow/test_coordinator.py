"""Coordinator tests: fixture-mode run path end-to-end + reproducibility (G2).

Offline (FixtureSource + SQLite memory). Live confirmation runs separately.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.decision_engine import SCORING_VERSION as CURRENT_SCORING_VERSION
from app.integrations.qloo_adapter import FixtureSource
from app.schemas.brief import DecisionBrief, HardConstraint
from app.services.persistence import get_engine, get_run_bundle, init_db
from app.workflow.coordinator import preflight_constraint_check, run_decision

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


def test_default_stamp_is_current_scoring_version() -> None:
    # Omitting the arg exercises the coordinator's default; the label must
    # always be the current one, not a stale literal.
    out = run_decision(_engine(), _brief(), FixtureSource(FIXTURES_DIR))
    assert out["report"]["scoring_version"] == CURRENT_SCORING_VERSION == "v0.2"


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


class _SharedPayloadSource:
    """Stub: one shared insights payload attached to every concept (live shape)."""

    is_live = False
    tag_urn = "urn:tag:mock:shared"

    def load(self, endpoint: str, params: dict[str, str]):
        from app.integrations.qloo_adapter import QlooPayload

        entity = {
            "name": "Mock Shared",
            "entity_id": "SHARED-ENTITY-ID",
            "popularity": 0.5,
            "tags": [{"tag_id": "urn:tag:mock:s"}],
            "types": ["urn:entity:place"],
        }
        if endpoint == "search":
            body = {"results": [dict(entity, name="Mock X", entity_id=f"E-{params.get('query', '?')}")]}
        else:
            body = {"success": True, "results": {"entities": [entity]}}
        return QlooPayload(
            endpoint=endpoint,
            query_params_redacted=dict(params),
            payload=body,
            source="fixture",
            fixture_mode=True,
        )


def test_shared_market_evidence_gets_concept_scoped_ids() -> None:
    eng = _engine()
    out = run_decision(eng, _brief(), _SharedPayloadSource(), scoring_version=SCORING_VERSION)
    assert out["state"] in ("COMPLETED", "COMPLETED_WITH_LIMITATIONS")
    bundle = get_run_bundle(eng, out["run_id"])
    ids = [e["evidence_id"] for e in bundle["evidence"]]
    assert len(ids) == len(set(ids))


def test_preflight_names_every_concept_that_cannot_satisfy_a_constraint() -> None:
    b = _brief()
    b.constraints = [
        HardConstraint(attribute="shelf_depth", value="shallow", note=None)
    ]
    with pytest.raises(ValueError) as excinfo:
        preflight_constraint_check(b)
    message = str(excinfo.value)
    # All three concepts lack the attribute: the message names them all.
    assert "A, B, C" in message
    assert "shelf_depth" in message


def test_preflight_passes_when_every_concept_declares_the_attribute() -> None:
    b = _brief()
    preflight_constraint_check(b)  # must not raise

