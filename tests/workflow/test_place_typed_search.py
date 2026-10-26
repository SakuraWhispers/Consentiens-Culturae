"""Place-typed concept searches (2026-10-26, owner decision; Wave-1 item 1).

Live finding + probe: /search accepts `types=urn:entity:place` (silences
non-place pollution — "a mixture of both" used to match book titles). The
coordinator injects the param into every LIVE search call at one chokepoint,
so researcher-planned and fallback-planned searches get it uniformly. Fixture
mode is untouched: synthetic runs keep their exact call shape.
"""

from __future__ import annotations

from pathlib import Path

from app.agents.schemas import AgentOutput
from app.integrations.qloo_adapter import QlooPayload
from app.services.persistence import get_engine, init_db
from app.workflow.coordinator import run_decision
from tests.workflow.test_coordinator import _brief

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


class _FakeSource:
    """Search-only source; search responses mirror the live /search envelope
    (results is a bare list). is_live toggles the injection behavior."""

    def __init__(self, live: bool) -> None:
        self.is_live = live
        self.calls: list[tuple[str, dict[str, str]]] = []

    def load(self, endpoint: str, params: dict[str, str]) -> QlooPayload:
        self.calls.append((endpoint, dict(params)))
        if endpoint == "search":
            body: dict = {
                "success": True,
                "results": [{
                    "name": params.get("query", ""),
                    "entity_id": "11111111-AAAA-BBBB-CCCC-DDDDDDDDDDDD",
                    "popularity": 0.6,
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


def _plan(names: list[str]):
    return AgentOutput(items=[(None, "search", {"query": n}) for n in names])


def _engine():
    eng = get_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


def test_live_search_calls_are_place_typed() -> None:
    source = _FakeSource(live=True)
    run_decision(_engine(), _brief(), source, researcher_fn=lambda names, hint: _plan(names))
    searches = [p for e, p in source.calls if e == "search"]
    # 3 planned concept searches + tie-break refinement searches on tied
    # concepts; EVERY live search call - planned or refined - is typed.
    assert len(searches) >= 3
    for params in searches:
        assert params["types"] == "urn:entity:place"
    # the concept queries themselves are untouched
    assert {p["query"] for p in searches} >= {c.name for c in _brief().concepts}


def test_non_live_and_fixture_shaped_search_is_untouched() -> None:
    source = _FakeSource(live=False)
    run_decision(_engine(), _brief(), source, researcher_fn=lambda names, hint: _plan(names))
    searches = [p for e, p in source.calls if e == "search"]
    assert len(searches) >= 3
    for params in searches:
        assert "types" not in params
