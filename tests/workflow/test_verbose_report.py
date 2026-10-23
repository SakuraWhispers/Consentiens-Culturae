"""Verbose-report tests (2026-10-22, Batch 3).

The human asked for a full verbose report written in words. The rules that
these tests pin:

* every run carries a verbose prose report;
* the prose is written by the reporter LLM ONLY after the critique stage
  actually succeeded, and its numbers are guarded: every number in the prose
  must come from the payload the reporter was given (worst case two calls -
  the retry names the offending number - then the deterministic template);
* the prose-only template fallback is produced honestly when no LLM report
  can be produced, and a limitation says so.
"""

from __future__ import annotations

from pathlib import Path

from app.integrations.qloo_adapter import FixtureSource
from app.schemas.brief import DecisionBrief
from app.services.persistence import get_engine, init_db
from app.workflow.coordinator import (
    _collect_allowed_numbers,
    _number_violations,
    run_decision,
)
from tests.workflow.test_coordinator import _brief

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _engine():
    eng = get_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


def _winning_concept(payload: dict) -> dict:
    ranked = [c for c in payload["concepts"] if c.get("weighted_total") is not None]
    ranked.sort(key=lambda c: (-c["weighted_total"], c["concept_id"]))
    return ranked[0]


def _good_report(payload: dict, repair_hint: str | None = None) -> dict:
    """Prose that only uses numbers from the payload."""
    top = _winning_concept(payload)
    return {
        "report": (
            f"{top['name']} leads the screening with a weighted total of "
            f"{top['weighted_total']:.1f}, rank {top['rank']}. "
            "Cultural affinity is not purchase intent and this is not a "
            "demand forecast."
        )
    }


def test_every_run_carries_a_verbose_report() -> None:
    eng = _engine()
    out = run_decision(eng, _brief(), FixtureSource(FIXTURES_DIR))
    verbose = out["report"]["verbose"]
    assert verbose["prose"], "the verbose report must not be empty"
    assert verbose["llm_written"] is False  # no LLM hooks -> the template
    assert verbose["template_fallback"] is True
    assert "Cultural affinity" in verbose["prose"] or "screening" in verbose["prose"].lower()


def test_strip_prose_fence_sheds_wrappers() -> None:
    """Audit fix (2026-10-23): the prose-fence strip used to exist as two
    separate copies (analyst wrapper + coordinator call site); after the
    dedupe there is one helper, pinned here."""
    from app.agents.analyst import strip_prose_fence

    assert strip_prose_fence("```markdown\nhello\n```") == "hello"
    assert strip_prose_fence("  plain prose  ") == "plain prose"


def test_a_fenced_report_comes_out_bare() -> None:
    """A reporter hook may fence its prose; the coordinator strips it with
    the shared helper so the stored report holds prose only."""

    def critic_fn(claims, score_summary, known_ids):
        return []

    def fenced_reporter(payload, repair_hint=None):
        good = _good_report(payload)["report"]
        return {"report": f"```markdown\n{good}\n```"}

    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        critic_fn=critic_fn, reporter_fn=fenced_reporter,
    )
    verbose = out["report"]["verbose"]
    assert verbose["llm_written"] is True
    assert verbose["attempts"] == 1
    assert "```" not in verbose["prose"]
    assert "leads the screening" in verbose["prose"]


def test_the_prose_is_llm_written_when_the_reporter_and_critique_succeed() -> None:
    def critic_fn(claims, score_summary, known_ids):
        return []

    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        critic_fn=critic_fn, reporter_fn=_good_report,
    )
    verbose = out["report"]["verbose"]
    assert verbose["llm_written"] is True
    assert verbose["template_fallback"] is False
    assert verbose["attempts"] == 1
    assert "Mock" in verbose["prose"] or "leads" in verbose["prose"]


def test_a_fabricated_number_is_caught_and_named_in_the_retry() -> None:
    calls: list[tuple[dict, str | None]] = []

    def reporter_fn(payload, repair_hint=None):
        calls.append((payload, repair_hint))
        if len(calls) == 1:
            return {"report": "The concept would capture 6995 percent of the market."}
        return _good_report(payload)

    def critic_fn(claims, score_summary, known_ids):
        return []

    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        critic_fn=critic_fn, reporter_fn=reporter_fn,
    )
    verbose = out["report"]["verbose"]
    assert verbose["llm_written"] is True
    assert verbose["attempts"] == 2
    assert "6995" in (calls[1][1] or ""), "the retry must name the offending number"
    assert "6995" not in verbose["prose"]


def test_a_reporter_that_keeps_fabricating_falls_back_to_the_template() -> None:
    def reporter_fn(payload, repair_hint=None):
        return {"report": "Sales will reach 3.5 million units within one year."}

    def critic_fn(claims, score_summary, known_ids):
        return []

    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        critic_fn=critic_fn, reporter_fn=reporter_fn,
    )
    verbose = out["report"]["verbose"]
    assert verbose["llm_written"] is False
    assert verbose["template_fallback"] is True
    assert verbose["attempts"] == 2
    assert "3.5 million" not in verbose["prose"], (
        "the fabricated prose must not reach the user"
    )
    assert any("verbose" in lim for lim in out["report"]["limitations"]), (
        "the fallback must be recorded as a limitation"
    )


def test_no_verbose_llm_without_a_successful_critique() -> None:
    def reporter_fn(payload, repair_hint=None):  # pragma: no cover - must not run
        raise AssertionError("the reporter must not run after a failed critique")

    def critic_fn(claims, score_summary, known_ids):
        raise RuntimeError("the critique provider is down")

    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        critic_fn=critic_fn, reporter_fn=reporter_fn,
    )
    verbose = out["report"]["verbose"]
    assert verbose["llm_written"] is False
    assert "critique" in verbose["template_reason"].lower()


# ---------------------------------------------------------------- guard unit


def test_the_guard_accepts_verbatim_and_rounded_payload_numbers() -> None:
    payload = {
        "concepts": [
            {"name": "Pouch", "weighted_total": 72.6667, "rank": 1, "coverage": 0.86}
        ],
        "sensitivity": {
            "statements": {"Pouch": "Top-ranked in 86% of tested preference scenarios"}
        },
        "tie": {"threshold": 0.5, "spread": 0.0},
    }
    allowed = _collect_allowed_numbers(payload)
    # Verbatim numbers, one-decimal rounding, and percent phrasing are allowed.
    assert _number_violations(
        "Pouch leads with a weighted total of 72.7, rank 1, coverage 86 percent, "
        "top-ranked in 86% of scenarios, gap 0.5.",
        allowed,
    ) == []
    # A fabricated number is caught.
    violations = _number_violations("It would capture 47 percent of the market.", allowed)
    assert [t for t, _ in violations] == ["47"]


def test_the_guard_ignores_criterion_labels_and_id_digit_runs() -> None:
    payload = {
        "claims": [
            {
                "claim_id": "claim-A-1",
                "text": "C1 favours the pouch",
                "evidence_ids": ["SEARCH-1b82af1ea8b24885a222df7b42f81764"],
            }
        ],
        "run_id": "1b82af1ea8b24885a222df7b42f81764",
    }
    allowed = _collect_allowed_numbers(payload)
    # "1b82af..." hex runs are not harvested into the allowed set; keys that
    # hold identifiers (claim_id, run_id, evidence_ids) are skipped outright.
    assert not any(v == 81764 for v in allowed)
    assert not any(v == 1 for v in allowed)
