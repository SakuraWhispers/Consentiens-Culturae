"""Workflow plumbing: the critic receives the per-concept evidence map
(Wave-1 item 6, owner-app 2026-10-26).

The coordinator passes a 4-element hook tuple — claims, score summary,
run-wide known ids, and the map concept_id -> that concept's evidence ids —
built from the run's own evidence records. The flat list stays 3rd so
existing hooks keep working.
"""

from __future__ import annotations

from pathlib import Path

from app.agents.schemas import AgentOutput
from app.integrations.qloo_adapter import QlooPayload
from app.services.persistence import get_engine, init_db, init_db
from app.workflow.coordinator import run_decision
from tests.workflow.test_coordinator import _brief

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


class _SearchOnlySource:
    """Live-protocol source: one record per concept search, empty insights."""

    is_live = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def load(self, endpoint: str, params: dict[str, str]) -> QlooPayload:
        self.calls.append((endpoint, dict(params)))
        if endpoint == "search":
            body: dict = {
                "success": True,
                "results": [{
                    "name": params.get("query", ""),
                    "entity_id": "22222222-AAAA-BBBB-CCCC-DDDDDDDDDDDD",
                    "popularity": 0.55,
                    "properties": {},
                    "tags": [{"name": "Mock", "tag_id": "urn:tag:mock:x"}],
                    "types": ["urn:entity:place"],
                }],
            }
        else:
            body = {"success": True, "results": {"entities": []}}
        return QlooPayload(
            endpoint=endpoint,
            query_params_redacted=dict(params),
            payload=body,
            source="qloo",
            fixture_mode=False,
        )


def test_critic_receives_the_per_concept_evidence_map() -> None:
    captured: dict = {}

    def critic(claims, score_summary, known_ids, known_ids_by_concept=None):
        captured["known_ids"] = list(known_ids)
        captured["map"] = known_ids_by_concept
        return {"items": [], "rejected": []}

    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    run_decision(
        engine,
        _brief(),
        _SearchOnlySource(),
        researcher_fn=lambda names, hint: AgentOutput(
            items=[(None, "search", {"query": n}) for n in names]
        ),
        critic_fn=critic,
    )

    the_map = captured["map"]
    assert the_map is not None, "critic received no per-concept map"
    assert set(the_map) == {c.concept_id for c in _brief().concepts}
    assert all(len(ids) >= 1 for ids in the_map.values())
    # flat list == union of the map values
    assert set(captured["known_ids"]) == {i for ids in the_map.values() for i in ids}
