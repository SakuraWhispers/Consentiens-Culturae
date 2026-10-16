"""Agent-path tests (G3): injected overclaim caught + revised, fallbacks hold.

Offline: injected LLM stand-ins, FixtureSource, SQLite memory.
"""

from __future__ import annotations

from pathlib import Path

from app.integrations.qloo_adapter import FixtureSource
from app.schemas.brief import DecisionBrief
from app.services.persistence import get_engine, get_run_bundle, init_db
from app.workflow.coordinator import run_decision
from tests.workflow.test_coordinator import _brief

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
SCORING_VERSION = "v0.1-g3"


def _engine():
    eng = get_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


def _analyst_with_overclaim(score_summary, evidence_summary, limitations, weights):
    return [
        {
            "claim_id": "claim-A",
            "concept_id": "A",
            "claim_type": "interpretation",
            "strength": "strong",
            "confidence": "high",
            "text": "Mock A drives purchase intent and will succeed because of its vibe.",
            "evidence_ids": [],
            "score_fields": ["A.weighted_total"],
            "audience_context": None,
        }
    ]


def _critic_flags_overclaim(claims, score_summary, known_ids):
    return [
        {
            "issue_code": "CAUSAL_OVERCLAIM",
            "severity": "minor",
            "affected_concept_id": "claim-A".split("-")[-1],
            "affected_claim_id": "claim-A",
            "evidence_ids": [],
            "explanation": "causal success claim without cited causal evidence",
            "suggested_action": "revise_wording",
        }
    ]


def _revise_softens(claims, findings):
    out = []
    for claim in claims:
        fixed = dict(claim)
        fixed["text"] = "Mock A shows the strongest available-evidence backing in this run."
        fixed["claim_type"] = "observation"
        out.append(fixed)
    return out


def test_injected_overclaim_caught_recorded_and_revised() -> None:
    eng = _engine()
    out = run_decision(
        eng,
        _brief(),
        FixtureSource(FIXTURES_DIR),
        scoring_version=SCORING_VERSION,
        analyst_fn=_analyst_with_overclaim,
        critic_fn=_critic_flags_overclaim,
        revise_fn=_revise_softens,
    )
    rep = out["report"]
    assert rep["analyst"]["llm_written"] is True
    assert rep["analyst"]["revision_count"] == 1
    codes = [f["issue_code"] for f in rep["critic_findings"]]
    assert "CAUSAL_OVERCLAIM" in codes
    revised = next(c for c in rep["claims"] if c["claim_id"] == "claim-A")
    assert "will succeed" not in revised["text"]
    bundle = get_run_bundle(eng, out["run_id"])
    assert bundle["run"]["state"] == out["state"]
    assert any(f["issue_code"] == "CAUSAL_OVERCLAIM" for f in bundle["critic"])


def test_garbage_analyst_falls_back_to_template() -> None:
    def bad_analyst(*a):
        return [{"claim_id": "x", "concept_id": "ZZZ"}]

    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        scoring_version=SCORING_VERSION, analyst_fn=bad_analyst,
    )
    assert out["report"]["analyst"]["llm_written"] is False
    assert any("template explanation used" in lim for lim in out["report"]["limitations"])


def test_off_allowlist_researcher_plan_rejected_with_fallback() -> None:
    def bad_researcher(names, tag):
        return [(None, "recs", {})]

    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        scoring_version=SCORING_VERSION, researcher_fn=bad_researcher,
    )
    assert out["state"] in ("COMPLETED", "COMPLETED_WITH_LIMITATIONS")
    assert any("allowlist" in lim for lim in out["report"]["limitations"])
