"""Report transparency blocks (2026-10-22, Batch 1).

The human asked to SEE what each stage did. These tests pin the report
blocks that make that possible:

* `research` — the retrieval plan (which endpoint, which params) and what it
  found, plus whether the agent plan or the deterministic plan was used;
* `critic` — the scope of the critique (claims reviewed, evidence available,
  the issue codes it may raise), so "0 findings" reads as "it ran and found
  nothing" instead of "it never ran";
* `stages` — how long each stage took;
* `tie` — a tie between the top concepts is detected and named instead of
  being papered over with a single winner;
* the bundle's evidence rows carry their entity name and provenance.
"""

from __future__ import annotations

from pathlib import Path

from app.integrations.qloo_adapter import FixtureSource
from app.schemas.brief import DecisionBrief
from app.services.persistence import get_engine, get_run_bundle, init_db
from app.workflow.coordinator import run_decision
from tests.workflow.test_coordinator import _brief

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _engine():
    eng = get_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


def test_the_report_exposes_what_the_researcher_did() -> None:
    eng = _engine()
    out = run_decision(eng, _brief(), FixtureSource(FIXTURES_DIR))
    research = out["report"]["research"]
    assert research["mode"] in ("agent", "deterministic")
    assert research["calls"], "the retrieval plan must be shown"
    for call in research["calls"]:
        assert call["endpoint"] in ("search", "insights")
        assert isinstance(call["params"], dict)
    assert research["evidence"]["total"] >= 3
    assert set(research["evidence"]["per_concept"]) == {"A", "B", "C"}


def test_the_report_exposes_the_scope_of_the_critique() -> None:
    eng = _engine()
    out = run_decision(eng, _brief(), FixtureSource(FIXTURES_DIR))
    critic = out["report"]["critic"]
    assert critic["claims_reviewed"] >= 1
    assert critic["evidence_records_available"] >= 1
    assert len(critic["issue_codes"]) == 10
    assert "UNSUPPORTED_CLAIM" in critic["issue_codes"]


def test_the_report_exposes_how_long_each_stage_took() -> None:
    eng = _engine()
    out = run_decision(eng, _brief(), FixtureSource(FIXTURES_DIR))
    stages = out["report"]["stages"]
    assert stages, "the stage timings must be present"
    names = [s["stage"] for s in stages]
    assert "RETRIEVING_EVIDENCE" in names
    assert "SCORING" in names
    for stage in stages:
        assert stage["seconds"] >= 0


def test_a_tie_between_the_top_concepts_is_detected_and_named() -> None:
    # The live run of 2026-10-22 had all three concepts on 60.6375 and still
    # declared one winner. The tie must now be visible.
    from app.services.decision_engine import score_concepts
    from app.schemas.brief import Weights

    scores = score_concepts(
        concept_ids=["A", "B", "C"],
        weights=Weights(c1=0.35, c2=0.2, c3=0.25, c5=0.2),
        raw_values={
            "A": {"C1": 0.5, "C2": 0.5, "C3": 0.5, "C5": 0.5},
            "B": {"C1": 0.5, "C2": 0.5, "C3": 0.5, "C5": 0.5},
            "C": {"C1": 0.2, "C2": 0.2, "C3": 0.2, "C5": 0.2},
        },
        hard_constraints=[],
        scoring_version="v0.1",
        concept_attributes={"A": {}, "B": {}, "C": {}},
    )
    from app.workflow.coordinator import _detect_tie

    tie = _detect_tie(scores)
    assert tie["detected"] is True
    assert set(tie["concepts"]) == {"A", "B"}
    assert tie["threshold"] == 0.5
    assert tie["spread"] == 0.0


def test_a_clear_winner_is_not_called_a_tie() -> None:
    from app.services.decision_engine import score_concepts
    from app.schemas.brief import Weights

    scores = score_concepts(
        concept_ids=["A", "B", "C"],
        weights=Weights(c1=0.35, c2=0.2, c3=0.25, c5=0.2),
        raw_values={
            "A": {"C1": 0.9, "C2": 0.9, "C3": 0.9, "C5": 0.9},
            "B": {"C1": 0.5, "C2": 0.5, "C3": 0.5, "C5": 0.5},
            "C": {"C1": 0.2, "C2": 0.2, "C3": 0.2, "C5": 0.2},
        },
        hard_constraints=[],
        scoring_version="v0.1",
        concept_attributes={"A": {}, "B": {}, "C": {}},
    )
    from app.workflow.coordinator import _detect_tie

    tie = _detect_tie(scores)
    assert tie["detected"] is False
    assert tie["concepts"] == ["A"]


def test_the_sensitivity_reports_ties_in_its_own_words() -> None:
    from app.services.robustness import analyze_sensitivity
    from app.schemas.brief import Weights

    result = analyze_sensitivity(
        concept_ids=["A", "B", "C"],
        raw_values={
            "A": {"C1": 0.5, "C2": 0.5, "C3": 0.5, "C5": 0.5},
            "B": {"C1": 0.5, "C2": 0.5, "C3": 0.5, "C5": 0.5},
            "C": {"C1": 0.2, "C2": 0.2, "C3": 0.2, "C5": 0.2},
        },
        hard_constraints=[],
        concept_attributes={"A": {}, "B": {}, "C": {}},
        base_weights=Weights(c1=0.35, c2=0.2, c3=0.25, c5=0.2),
    )
    ties = result["tie_statements"]
    assert "A" in ties and "B" in ties
    assert "Tied with" in ties["A"]
    assert "of tested preference scenarios" in ties["A"]


def test_the_bundle_evidence_rows_carry_their_name_and_provenance() -> None:
    eng = _engine()
    out = run_decision(eng, _brief(), FixtureSource(FIXTURES_DIR))
    bundle = get_run_bundle(eng, out["run_id"])
    assert bundle["evidence"]
    row = bundle["evidence"][0]
    for key in (
        "evidence_id",
        "qloo_entity_id",
        "entity_name",
        "entity_subtype",
        "popularity",
        "match_quality",
        "coverage_status",
        "endpoint_or_operation",
        "query_params_redacted",
        "source",
        "fixture_mode",
        "limitations",
    ):
        assert key in row, f"the evidence row must carry {key}"


def test_the_report_says_when_the_concepts_are_tied_end_to_end() -> None:
    # Same brief, but the two concepts get identical evidence.
    payload = _brief().model_dump()
    payload["concepts"][0]["name"] = payload["concepts"][1]["name"]
    brief = DecisionBrief(**payload)
    eng = _engine()
    out = run_decision(eng, brief, FixtureSource(FIXTURES_DIR))
    tie = out["report"]["tie"]
    assert tie["detected"] is True
    assert len(tie["concepts"]) >= 2
    # The winner is still reported (the engine's tie-break), but the tie is
    # named so the page cannot imply a clear difference.
    assert out["report"]["winner"] in tie["concepts"]
