"""Critic/analyst source tagging (2026-10-22).

The results page shows two boxes: what the analyst found, and what the critic
challenged. For the second box to be honest it must say WHO made each
finding: the LLM critic or the rule checks.
"""

from __future__ import annotations

from pathlib import Path

from app.integrations.qloo_adapter import FixtureSource
from app.services.persistence import get_engine, init_db
from app.workflow.coordinator import run_decision
from tests.workflow.test_coordinator import _brief

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"

_CLAIM = {
    "claim_id": "claim-A", "concept_id": "A", "claim_type": "observation",
    "strength": "moderate", "confidence": "medium",
    "text": "Mock A ranks second on the available evidence.",
    "evidence_ids": [], "score_fields": [], "audience_context": None,
}

_FINDING = {
    "issue_code": "CAUSAL_OVERCLAIM", "severity": "minor",
    "affected_concept_id": "A", "affected_claim_id": "claim-A",
    "evidence_ids": [], "explanation": "causal phrasing without cited causal evidence",
    "suggested_action": "qualify",
}


def _engine():
    eng = get_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


def test_llm_critic_findings_are_tagged_as_llm() -> None:
    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        analyst_fn=lambda *a: [dict(_CLAIM)],
        critic_fn=lambda *a: [dict(_FINDING)],
    )
    rep = out["report"]
    assert rep["critic"]["llm_written"] is True
    assert rep["critic"]["llm_findings"] == 1
    assert rep["critic"]["rule_findings"] == 0
    assert all(f["source"] == "llm" for f in rep["critic_findings"])


def test_rule_critic_findings_are_tagged_as_rules() -> None:
    # No critic hook at all: the rule checks are the only critic.
    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        analyst_fn=lambda *a: [dict(_CLAIM)],
    )
    rep = out["report"]
    assert rep["critic"]["llm_written"] is False
    for finding in rep["critic_findings"]:
        assert finding["source"] == "rules"


def test_the_report_always_carries_the_critic_meta() -> None:
    eng = _engine()
    out = run_decision(eng, _brief(), FixtureSource(FIXTURES_DIR))
    assert "critic" in out["report"]
    assert set(out["report"]["critic"]) == {
        "llm_written",
        "findings_count",
        "llm_findings",
        "rule_findings",
    }
