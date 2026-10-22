"""Tie-break tests (2026-10-22, Batch 2).

A live run had all three concepts on exactly the same total. The human asked:
when that happens, go and look harder - more Qloo, more LLM - and say which
one the evidence actually separates.

These tests pin the behaviour:

* a tie triggers the tie-break: extra Qloo calls for the tied concepts only,
  inside the run's call budget;
* an entity that is already known is NOT added twice (the same entity is the
  same entity - it would otherwise be counted twice);
* the totals are recomputed with the new evidence and the report shows the
  before/after;
* if the evidence still cannot separate them, the report says so, and the
  focused LLM comparison is recorded;
* the critique reviews the tie-break claims as well.
"""

from __future__ import annotations

from pathlib import Path

from app.integrations.qloo_adapter import FixtureSource
from app.schemas.brief import DecisionBrief
from app.services.persistence import get_engine, init_db
from app.workflow.coordinator import run_decision
from tests.workflow.test_coordinator import _brief

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _engine():
    eng = get_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


def _tied_brief() -> DecisionBrief:
    """Two concepts with the same name get the same evidence -> a tie."""
    payload = _brief().model_dump()
    payload["concepts"][0]["name"] = payload["concepts"][1]["name"]
    return DecisionBrief(**payload)


def _tiebreak_claim(concept_id: str) -> dict:
    return {
        "claim_id": f"tiebreak-{concept_id}",
        "concept_id": concept_id,
        "claim_type": "interpretation",
        "strength": "moderate",
        "confidence": "medium",
        "text": "The second round of evidence separates the two tied concepts.",
        "evidence_ids": [],
        "score_fields": [],
        "audience_context": None,
    }


def test_a_tie_triggers_the_tie_break_and_is_reported() -> None:
    eng = _engine()
    out = run_decision(eng, _tied_brief(), FixtureSource(FIXTURES_DIR))
    rep = out["report"]
    tb = rep["tiebreak"]
    assert tb["detected"] is True
    # The tied concepts are exactly the RANKED ones (the fixture serves the
    # same entities for every concept, so the feasible ones end up level).
    ranked = {r["concept_id"] for r in rep["ranks"] if r["status"] == "RANKED"}
    assert set(tb["concepts"]) == ranked
    assert tb["extra_calls"] >= 1, "the tie-break must look harder with Qloo"
    assert "before" in tb and "after" in tb
    assert set(tb["before"]) == set(tb["concepts"])
    assert tb["note"], "the tie-break must explain what it did"


def test_the_tie_break_stays_inside_the_call_budget() -> None:
    eng = _engine()
    out = run_decision(
        eng, _tied_brief(), FixtureSource(FIXTURES_DIR), max_live_calls=4
    )
    tb = out["report"]["tiebreak"]
    # The base plan already used 3 calls; the tie-break may not push the run
    # past the budget.
    assert tb["extra_calls"] <= 1


def test_an_entity_that_is_already_known_is_not_added_twice() -> None:
    eng = _engine()
    out = run_decision(eng, _tied_brief(), FixtureSource(FIXTURES_DIR))
    tb = out["report"]["tiebreak"]
    assert tb["new_entities"] == 0, (
        "the fixture serves the same entities for the refined query, "
        "so nothing new may be counted"
    )
    assert tb["known_entities_skipped"] >= 1


def test_a_tie_that_survives_is_reported_as_such() -> None:
    eng = _engine()
    out = run_decision(eng, _tied_brief(), FixtureSource(FIXTURES_DIR))
    tb = out["report"]["tiebreak"]
    assert tb["resolved"] is False
    assert tb["before"]["A"] == tb["after"]["A"], "no new evidence, no change"
    assert "cannot" in tb["note"].lower() or "still" in tb["note"].lower()


def test_the_focused_comparison_is_recorded_and_reviewed_by_the_critique() -> None:
    seen_claims: list[list[dict]] = []

    def tiebreak_fn(tied, evidence_summary, weights, before, after):
        return [_tiebreak_claim(c["concept_id"]) for c in tied]

    def critic(claims, score_summary, known_ids):
        seen_claims.append(list(claims))
        return []

    eng = _engine()
    out = run_decision(
        eng, _tied_brief(), FixtureSource(FIXTURES_DIR),
        tiebreak_fn=tiebreak_fn, critic_fn=critic,
    )
    tb = out["report"]["tiebreak"]
    assert len(tb["comparison"]) == len(tb["concepts"])
    assert {c["concept_id"] for c in tb["comparison"]} == set(tb["concepts"])
    # The critique reviews the tie-break claims as well.
    assert any(
        any(c.get("claim_id", "").startswith("tiebreak-") for c in claims)
        for claims in seen_claims
    )


def test_without_a_tie_nothing_extra_happens() -> None:
    def tiebreak_fn(tied, evidence_summary, weights, before, after):
        raise AssertionError("the tie-break must not run without a tie")

    # Only one concept can pass the hard constraint, so there is nothing to
    # tie and the tie-break must stay out of the way.
    payload = _brief().model_dump()
    payload["concepts"][1]["attributes"] = {"material": "virgin-plastic"}
    payload["concepts"][2]["attributes"] = {"material": "virgin-plastic"}
    brief = DecisionBrief(**payload)

    eng = _engine()
    out = run_decision(
        eng, brief, FixtureSource(FIXTURES_DIR), tiebreak_fn=tiebreak_fn
    )
    rep = out["report"]
    assert rep["tiebreak"]["detected"] is False
    assert rep["tiebreak"]["extra_calls"] == 0
