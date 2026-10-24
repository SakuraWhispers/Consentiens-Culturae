"""Per-concept critique notes (2026-10-24, Feature B).

The human asked for a critique focused on each concept's drawbacks, plus a
5-6 line winning-concept note (data + context, tight and honest). The rules
these tests pin:

* every run carries `report.critic.concept_notes` - one note per concept id
  and a winner note;
* the LLM's notes are id-checked (unknown ids rejected), length-capped and
  number-guarded like the verbose report (two attempts, then the template);
* the deterministic template is produced honestly whenever the LLM cannot
  write, and the run says so (template_used).
"""

from __future__ import annotations

from pathlib import Path

from app.integrations.qloo_adapter import FixtureSource
from app.services.persistence import get_engine, init_db
from app.workflow.coordinator import run_decision
from tests.workflow.test_coordinator import _brief

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _engine():
    eng = get_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


def _notes(report: dict) -> dict:
    return report["critic"]["concept_notes"]


def _run(eng, concept_critic_fn):
    """A completed LLM critique is the gate for the concept critic, so every
    hook test also takes a (silent) critic hook - the reporter rule."""
    return run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        critic_fn=lambda *a: [], concept_critic_fn=concept_critic_fn,
    )


def test_every_run_carries_per_concept_notes() -> None:
    eng = _engine()
    out = run_decision(eng, _brief(), FixtureSource(FIXTURES_DIR))
    block = _notes(out["report"])
    assert set(block["notes"]) == {"A", "B", "C"}
    assert all(n.strip() for n in block["notes"].values())
    assert block["winner_note"]
    assert block["llm_written"] is False
    assert block["template_used"] is True


def test_llm_notes_survive_with_unknown_ids_and_are_used() -> None:
    def concept_critic_fn(payload, repair_hint=None):
        return {
            "notes": {
                "A": "Weak evidence coverage for this concept.",
                "B": "The claims overreach without cited support.",
                "C": "Level with the leader; no separation in the data.",
            },
            "winner_note": "The winner leads on the computed totals only.",
        }

    eng = _engine()
    out = _run(eng, concept_critic_fn)
    block = _notes(out["report"])
    assert block["llm_written"] is True
    assert block["template_used"] is False
    assert block["notes"]["A"] == "Weak evidence coverage for this concept."


def test_unknown_concept_id_is_rejected_twice_then_the_template_is_used() -> None:
    def concept_critic_fn(payload, repair_hint=None):
        return {
            "notes": {"A": "ok", "B": "ok", "Z": "not a concept"},
            "winner_note": "winner",
        }

    eng = _engine()
    out = _run(eng, concept_critic_fn)
    block = _notes(out["report"])
    assert block["llm_written"] is False
    assert block["template_used"] is True
    limitations = out["report"]["limitations"]
    assert any(
        "concept notes" in lim for lim in limitations
    ), "the fallback must be recorded, never silent"


def test_an_invented_number_fails_the_guard_then_the_template_is_used() -> None:
    def concept_critic_fn(payload, repair_hint=None):
        # An invented market share: 137% appears nowhere in the payload.
        return {
            "notes": {
                "A": "This concept holds a 137 percent share of the audience.",
                "B": "Thin coverage holds it back.",
                "C": "Level with the leader on the computed totals.",
            },
            "winner_note": "The winner leads on computed numbers alone.",
        }

    eng = _engine()
    out = _run(eng, concept_critic_fn)
    block = _notes(out["report"])
    assert block["llm_written"] is False, "guarded-out notes must not reach the report"
    assert "137" not in block["notes"]["A"]
    assert block["template_used"] is True
