"""Evidence-ID and critic-rule tests (2026-10-22).

Live finding: the analyst prompt forbade citing evidence IDs (the payload had
counts only) and BOTH critics then flagged every claim for having no evidence
IDs — the system required the analyst to produce exactly what the critic was
required to flag. All 120 evidence records were available; the critique was
self-contradictory.

These tests pin the fixed behaviour:

* the analyst payload carries the REAL evidence IDs per concept (capped), so a
  claim can cite evidence that exists and be checked;
* the rule critic no longer flags a claim merely for having an empty ID list;
  it still flags a concept that genuinely has no evidence;
* a claim citing an invented ID is dropped and reported (unchanged hard rule);
* the report carries the reason a concept is INFEASIBLE.
"""

from __future__ import annotations

from pathlib import Path

from app.integrations.qloo_adapter import FixtureSource
from app.services.persistence import get_engine, init_db
from app.workflow.coordinator import run_decision
from tests.workflow.test_coordinator import _brief

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"

# A claim in the shape the analyst produces: a count in the text, and the
# real evidence IDs of the concept it is about.
_CLAIM_WITH_ID = {
    "claim_id": "claim-A", "concept_id": "A", "claim_type": "observation",
    "strength": "moderate", "confidence": "medium",
    "text": "Mock A ranks second on the available evidence.",
    "evidence_ids": [], "score_fields": [], "audience_context": None,
}


def _engine():
    eng = get_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


def test_analyst_payload_carries_the_real_evidence_ids() -> None:
    seen: list[dict] = []

    def analyst(score_summary, evidence_summary, limitations, weights):
        seen.append(evidence_summary)
        return [dict(_CLAIM_WITH_ID)]

    eng = _engine()
    run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        analyst_fn=analyst,
    )
    payload = seen[0]
    assert set(payload) == {"A", "B", "C"}
    for cid, entry in payload.items():
        assert entry["available"] >= 0 and entry["total"] >= entry["available"]
        ids = entry["evidence_ids"]
        assert ids, f"{cid} must carry the real evidence ids"
        assert len(ids) <= 12, "the id list is capped"
        assert all(isinstance(i, str) and i for i in ids)


def test_claim_citing_a_real_evidence_id_is_accepted() -> None:
    captured: list[dict] = []

    def analyst(score_summary, evidence_summary, limitations, weights):
        ids = evidence_summary["A"]["evidence_ids"]
        captured.append({"ids": ids})
        return [{**_CLAIM_WITH_ID, "evidence_ids": list(ids[:2])}]

    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        analyst_fn=analyst,
    )
    rep = out["report"]
    assert rep["analyst"]["llm_written"] is True
    assert len(rep["claims"]) == 1
    assert rep["claims"][0]["evidence_ids"], "the cited ids must survive into the report"
    assert not any("claim rejected" in lim for lim in rep["limitations"])


def test_claim_citing_an_invented_evidence_id_is_dropped_and_reported() -> None:
    def analyst(score_summary, evidence_summary, limitations, weights):
        return [{**_CLAIM_WITH_ID, "evidence_ids": ["not-a-real-evidence-id"]}]

    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        analyst_fn=analyst,
    )
    rep = out["report"]
    # The invented id never reaches the report; the stage falls back to the
    # template (which cites no ids) and says so.
    assert all(
        "not-a-real-evidence-id" not in (c.get("evidence_ids") or [])
        for c in rep["claims"]
    )
    # The limitation must NAME the reason (an invented evidence id), not just
    # that something failed.
    assert any(
        "unknown evidence IDs" in lim for lim in rep["limitations"]
    ), rep["limitations"]
    assert rep["explanation_template"] is True


def test_rule_critic_does_not_flag_empty_ids_when_evidence_exists() -> None:
    # The false positive: every claim had evidence_ids=[] and the rule critic
    # said "no available evidence backs this concept's claim".
    def analyst(score_summary, evidence_summary, limitations, weights):
        return [dict(_CLAIM_WITH_ID)]

    eng = _engine()
    out = run_decision(
        eng, _brief(), FixtureSource(FIXTURES_DIR),
        analyst_fn=analyst,
    )
    rep = out["report"]
    missing = [
        f for f in rep["critic_findings"]
        if f["issue_code"] == "MISSING_EVIDENCE"
        and "no available evidence backs" in f["explanation"]
    ]
    assert missing == [], "the rule critic must not fire when the concept HAS evidence"


def test_a_brief_whose_constraints_cannot_be_checked_stops_at_the_door() -> None:
    """The 2026-10-23 decision: this scenario used to burn a whole run and
    then announce every concept INFEASIBLE. It must now be rejected with a
    message naming the missing attributes - BEFORE the run row exists."""
    from app.schemas.brief import DecisionBrief

    brief = _brief()
    payload = brief.model_dump()
    payload["constraints"] = [{"attribute": "price_band", "value": "under-25"}]
    for concept in payload["concepts"]:
        concept["attributes"] = {}  # the website used to send no attributes
    hard = DecisionBrief(**payload)

    eng = _engine()
    with pytest.raises(ValueError) as excinfo:
        run_decision(eng, hard, FixtureSource(FIXTURES_DIR))
    message = str(excinfo.value)
    assert "'price_band'" in message
    assert "do not declare" in message



def test_infeasible_reason_is_absent_for_a_ranked_concept() -> None:
    eng = _engine()
    out = run_decision(eng, _brief(), FixtureSource(FIXTURES_DIR))
    for rank in out["report"]["ranks"]:
        if rank["status"] == "RANKED":
            assert not rank.get("reason")
