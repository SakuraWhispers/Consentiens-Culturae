"""Coordinator resilience tests (2026-10-20 live-run fixes).

These cover the behaviour the live run lacked:

* one malformed item no longer takes the whole stage down (a plan call, a
  claim, a finding);
* the retry is INFORMED — the validation error is handed back to the model
  instead of repeating the identical prompt at temperature 0;
* a rejected agent output is persisted as a workflow event, so a live
  failure can be diagnosed from the database instead of guessed at.

Offline: injected hook stand-ins, FixtureSource, SQLite in memory.
"""

from __future__ import annotations

from pathlib import Path

from app.integrations.qloo_adapter import FixtureSource
from app.services.persistence import get_engine, get_run_bundle, init_db
from app.workflow.coordinator import run_decision
from tests.workflow.test_coordinator import _brief

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _engine():
    eng = get_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


_GOOD_CLAIM = {
    "claim_id": "claim-A", "concept_id": "A", "claim_type": "observation",
    "strength": "moderate", "confidence": "medium",
    "text": "Mock A ranks second on the available evidence.",
    "evidence_ids": [], "score_fields": [], "audience_context": None,
}

_GOOD_FINDING = {
    "issue_code": "CAUSAL_OVERCLAIM", "severity": "minor",
    "affected_concept_id": "A", "affected_claim_id": "claim-A",
    "evidence_ids": [], "explanation": "causal phrasing without cited causal evidence",
    "suggested_action": "revise_wording",
}


def test_researcher_one_bad_call_keeps_the_good_ones() -> None:
    """A malformed call is dropped and REPORTED; the rest of the plan runs."""
    attempts: list[int] = []

    def researcher(names, category):
        attempts.append(1)
        return [
            ("A", "search", {"query": "Mock Studio Notebooks"}),
            # insights is planned by the code itself since 2026-10-24
            (None, "insights", {"filter.type": "urn:entity:place"}),
        ]

    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        researcher_fn=researcher,
    )
    limits = out["report"]["limitations"]
    assert any("planned by the code itself" in lim for lim in limits)
    # The plan was usable, so no second LLM call was needed.
    assert len(attempts) == 1
    assert out["state"] in ("COMPLETED", "COMPLETED_WITH_LIMITATIONS")


def test_researcher_retry_is_informed_when_the_whole_plan_is_rejected() -> None:
    """The second attempt is told WHAT was wrong, so it can be corrected."""
    seen_hints: list[str | None] = []

    def researcher(names, tag, repair_hint=None):
        seen_hints.append(repair_hint)
        if repair_hint is None:
            return [(None, "recs", {})]
        return [(None, "search", {"query": "Mock Studio Notebooks"})]

    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        researcher_fn=researcher,
    )
    assert len(seen_hints) == 2
    assert seen_hints[0] is None
    assert seen_hints[1] and "rejected" in seen_hints[1]
    assert out["state"] in ("COMPLETED", "COMPLETED_WITH_LIMITATIONS")


def test_critic_one_bad_finding_keeps_the_good_ones() -> None:
    """The live failure: severity "medium" killed the whole critique."""

    def critic(claims, score_summary, known_ids, known_ids_by_concept=None):
        return [
            _GOOD_FINDING,
            {**_GOOD_FINDING, "affected_claim_id": "claim-B", "severity": "catastrophic"},
        ]

    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        analyst_fn=lambda *a: [dict(_GOOD_CLAIM)],
        critic_fn=critic,
    )
    rep = out["report"]
    assert rep["llm_written"] is True
    assert len(rep["critic_findings"]) == 1
    assert rep["critic_findings"][0]["issue_code"] == "CAUSAL_OVERCLAIM"
    assert any("finding" in lim for lim in rep["limitations"])


def test_critic_retry_is_informed_and_the_second_attempt_is_used() -> None:
    seen_hints: list[str | None] = []

    def critic(claims, score_summary, known_ids, known_ids_by_concept=None, repair_hint=None):
        seen_hints.append(repair_hint)
        if repair_hint is None:
            raise ValueError("severity 'medium' is not one of major, minor, info")
        return [dict(_GOOD_FINDING)]

    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        analyst_fn=lambda *a: [dict(_GOOD_CLAIM)],
        critic_fn=critic,
    )
    rep = out["report"]
    assert len(seen_hints) == 2
    assert seen_hints[0] is None
    assert seen_hints[1] and "severity" in seen_hints[1]
    assert len(rep["critic_findings"]) == 1
    assert not any("invalid twice" in lim for lim in rep["limitations"])


def test_analyst_one_bad_claim_keeps_the_good_ones() -> None:
    def analyst(score_summary, evidence_summary, limitations, weights):
        return [
            dict(_GOOD_CLAIM),
            {**_GOOD_CLAIM, "claim_id": "claim-Z", "concept_id": "ZZZ"},
        ]

    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        analyst_fn=analyst,
    )
    rep = out["report"]
    assert rep["analyst"]["llm_written"] is True
    assert [c["claim_id"] for c in rep["claims"]] == ["claim-A"]
    assert any("claim rejected" in lim for lim in rep["limitations"])


def test_rejected_agent_output_is_persisted_for_diagnosis() -> None:
    def critic(claims, score_summary, known_ids, known_ids_by_concept=None):
        return [
            _GOOD_FINDING,
            {**_GOOD_FINDING, "affected_claim_id": "claim-B", "severity": "catastrophic"},
        ]

    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        analyst_fn=lambda *a: [dict(_GOOD_CLAIM)],
        critic_fn=critic,
    )
    bundle = get_run_bundle(eng, out["run_id"])
    rejected_events = [
        e for e in bundle["events"] if e["event_type"] == "agent_output_rejected"
    ]
    assert rejected_events, "the rejected finding must leave an audit trail"
    detail = rejected_events[0]["detail"]
    assert detail["stage"] == "critic"
    assert any("severity" in text for text in detail["rejected"])


def test_critic_all_findings_dropped_falls_back_to_deterministic_checks() -> None:
    """If nothing the critic produced is usable, the safety net takes over."""

    def critic(claims, score_summary, known_ids, known_ids_by_concept=None):
        return [{**_GOOD_FINDING, "severity": "catastrophic"}]

    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        critic_fn=critic,
    )
    rep = out["report"]
    assert any("deterministic checks used" in lim for lim in rep["limitations"])
    assert rep["critic_findings"] == []


def test_nothing_surviving_still_falls_back_to_the_deterministic_path() -> None:
    def analyst(score_summary, evidence_summary, limitations, weights):
        return [{**_GOOD_CLAIM, "concept_id": "ZZZ"}]

    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        analyst_fn=analyst,
    )
    rep = out["report"]
    assert rep["analyst"]["llm_written"] is False
    assert rep["explanation_template"] is True
    assert any("template explanation used" in lim for lim in rep["limitations"])
