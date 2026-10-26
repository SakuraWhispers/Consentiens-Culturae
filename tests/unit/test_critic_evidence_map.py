"""Critic payload: per-concept evidence map (Wave-1 item 6, owner-app 2026-10-26).

The critic is asked to check that a claim cites ITS OWN concept's evidence,
but it only saw a concept-less id list. It now also receives the map
concept_id -> that concept's evidence ids; the flat run-wide list stays for
aggregate claims and backward compatibility.
"""

from __future__ import annotations

import app.agents.analyst as analyst
from app.agents.analyst import review_claims_llm


def test_payload_carries_both_the_flat_list_and_the_map() -> None:
    captured: dict = {}

    def fake(api_key, model, system, user_payload, *args, **kwargs):
        captured["payload"] = user_payload
        return {"findings": [], "rejected": []}

    orig = analyst.complete_json
    analyst.complete_json = fake  # type: ignore[assignment]
    try:
        out = review_claims_llm(
            "k", "m", [{"concept_id": "A", "text": "x"}], {"A": 1.0}, ["ev-1"],
            evidence_by_concept={"A": ["ev-1", "ev-2"], "B": []},
        )
    finally:
        analyst.complete_json = orig  # type: ignore[assignment]
    assert captured["payload"]["known_evidence_ids"] == ["ev-1"]
    assert captured["payload"]["known_evidence_by_concept"] == {
        "A": ["ev-1", "ev-2"], "B": [],
    }
    assert out.findings == []
    assert out.rejected == []


def test_payload_stays_flat_when_no_map_is_given() -> None:
    captured: dict = {}

    def fake(api_key, model, system, user_payload, *args, **kwargs):
        captured["payload"] = user_payload
        return {"findings": [], "rejected": []}

    orig = analyst.complete_json
    analyst.complete_json = fake  # type: ignore[assignment]
    try:
        review_claims_llm("k", "m", [], {}, ["ev-1"])
    finally:
        analyst.complete_json = orig  # type: ignore[assignment]
    assert "known_evidence_by_concept" not in captured["payload"]
    assert captured["payload"]["known_evidence_ids"] == ["ev-1"]
