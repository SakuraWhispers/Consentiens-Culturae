"""Dynamic category selection (2026-10-24, owner decision).

The fixed demo category is gone: the researcher names the category, and the
CODE resolves it to a place-category tag via the docs-verified /v2/tags
endpoint (2026-10-16 live verification), then makes the shared market
insights call itself. A model never writes a tag URN. Pins:

* the tags call carries the researcher's category phrase (filter.query);
* the insights call carries the RESOLVED place-category URN (most popular);
* an unresolvable category is a recorded limitation and a skipped insights
  call - never a guessed tag;
* no category anywhere -> skip + limitation;
* a too-small call budget -> skip + limitation.
"""

from __future__ import annotations

from pathlib import Path

from app.agents.schemas import AgentOutput
from app.integrations.qloo_adapter import QlooPayload
from app.services.persistence import get_engine, init_db
from app.workflow.coordinator import run_decision
from tests.workflow.test_coordinator import _brief

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


class _FakeLiveSource:
    """Live-protocol source with scripted /v2/tags responses."""

    is_live = True

    def __init__(self, tags: list[dict]) -> None:
        self.tags = tags
        self.calls: list[tuple[str, dict[str, str]]] = []

    def load(self, endpoint: str, params: dict[str, str]) -> QlooPayload:
        self.calls.append((endpoint, dict(params)))
        if endpoint == "tags":
            body: dict = {"success": True, "results": {"tags": self.tags}}
        elif endpoint == "insights":
            body = {"success": True, "results": {"entities": []}}
        else:  # one synthetic search hit per query (shape-mirror of /search)
            body = {
                "success": True,
                "results": [{
                    "name": params.get("query", ""),
                    "entity_id": "11111111-AAAA-BBBB-CCCC-DDDDDDDDDDDD",
                    "popularity": 0.6,
                    "properties": {},
                    "tags": [{"name": "Mock", "tag_id": "urn:tag:mock:x", "value": "urn:tag:mock:x"}],
                    "types": ["urn:entity:brand"],
                    "disambiguation": "test fixture",
                }],
            }
        return QlooPayload(
            endpoint=endpoint,
            query_params_redacted=dict(params),
            payload=body,
            source="qloo",
            fixture_mode=False,
        )


_TAGS = [
    {"id": "urn:tag:genre:place:generic_term", "popularity": 0.99},
    {"id": "urn:tag:category:place:pizza_place", "name": "Pizza Place", "popularity": 0.9},
    {"id": "urn:tag:category:place:convenience_store", "name": "Convenience Store", "popularity": 0.7},
]


def _search_plan(names: list[str], category: str | None):
    return AgentOutput(
        items=[
            (None, "search", {"query": n}) for n in names
        ],
        category=category,
    )


def _run(eng, source, researcher):
    return run_decision(eng, _brief(), source, researcher_fn=researcher)


def test_researcher_category_resolves_and_drives_the_insights_call() -> None:
    source = _FakeLiveSource(_TAGS)

    def researcher(names, category_hint):
        # Briefs no longer carry a fixed demo category.
        assert category_hint is None
        return _search_plan(names, "pizza places")

    out = _run(_engine(), source, researcher)
    tag_calls = [p for e, p in source.calls if e == "tags"]
    assert tag_calls == [{"filter.query": "pizza places"}]
    insights = [p for e, p in source.calls if e == "insights"]
    assert len(insights) == 1
    # The most popular PLACE-category tag wins; the genre tag is ignored.
    assert insights[0]["filter.tags"] == "urn:tag:category:place:pizza_place"
    assert insights[0]["filter.type"] == "urn:entity:place"
    assert not any("insights call was skipped" in lim for lim in out["report"]["limitations"])


def test_an_unresolvable_category_skips_the_insights_call_and_is_recorded() -> None:
    source = _FakeLiveSource([{"id": "urn:tag:genre:place:whatever", "popularity": 0.9}])

    def researcher(names, category_hint):
        return _search_plan(names, "handmade kites")

    out = _run(_engine(), source, researcher)
    assert [e for e, _ in source.calls].count("insights") == 0
    assert any(
        "resolved to no place-category tag" in lim
        for lim in out["report"]["limitations"]
    )
    assert out["state"] in ("COMPLETED", "COMPLETED_WITH_LIMITATIONS")


def test_no_category_anywhere_skips_the_insights_call() -> None:
    source = _FakeLiveSource(_TAGS)

    def researcher(names, category_hint):
        return _search_plan(names, None)

    out = _run(_engine(), source, researcher)
    assert "tags" not in [e for e, _ in source.calls]
    assert any("no category named" in lim for lim in out["report"]["limitations"])


def test_a_small_call_budget_skips_resolution_instead_of_overrunning() -> None:
    source = _FakeLiveSource(_TAGS)

    def researcher(names, category_hint):
        return _search_plan(names, "pizza places")

    eng = _engine()
    out = run_decision(
        eng, _brief(), source, researcher_fn=researcher, max_live_calls=2,
    )
    assert "tags" not in [e for e, _ in source.calls]
    assert any(
        "budget too small" in lim for lim in out["report"]["limitations"]
    )


def _engine():
    eng = get_engine("sqlite:///:memory:")
    init_db(eng)
    return eng
