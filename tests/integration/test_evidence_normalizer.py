"""Integration-level tests: Qloo adapter + evidence normalizer against fixtures.

Offline by design (AGENTS.md section 7). Live Qloo calls never run here.
Fixture policy (SCOPE.md decision log 2026-10-16): only hand-written synthetic
fixtures; tests/fixtures/recorded/ is gitignored and refused by the loader.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.integrations.qloo_adapter import FixtureError, FixtureSource, load_fixture_file
from app.integrations.qloo_adapter import QlooPayload
from app.services.evidence_normalizer import normalize_response

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"

SYNTHETIC_SUCCESS = "fixture_search_synthetic_success.json"
ADV_MISSING = "fixture_adv_missing_fields.json"
ADV_NO_MATCH = "fixture_adv_no_match.json"
ADV_MALFORMED = "fixture_adv_malformed.json"


def _payload_records(filename: str, endpoint: str = "search", intended_name: str | None = None):
    raw = load_fixture_file(FIXTURES_DIR / filename)
    payload = QlooPayload(
        endpoint=endpoint,
        query_params_redacted=dict(raw["request_params"]),
        payload=raw["response"],
        source="fixture",
        fixture_mode=True,
    )
    return normalize_response(payload, intended_name=intended_name)


# ---------- fixture envelope rules ----------


def test_every_committed_fixture_has_labeled_meta() -> None:
    files = sorted(p for p in FIXTURES_DIR.glob("fixture_*.json"))
    assert files, "expected at least one committed fixture"
    for path in files:
        raw = load_fixture_file(path)  # raises FixtureError if unlabeled
        meta = raw["_meta"]
        assert meta["fixture"] is True
        assert meta["source"] == "hand-written"
        assert "NO real Qloo data" in meta["note"]


def test_recorded_fixture_source_is_refused_by_synthetic_loader(tmp_path: Path) -> None:
    # Simulates that a recorded response can never be loaded through the
    # synthetic loader (fixture policy: SCOPE.md decision log 2026-10-16).
    recorded = tmp_path / "fixture_recorded_probe.json"
    recorded.write_text(
        '{"_meta": {"fixture": true, "source": "recorded"}, "response": {"results": {"entities": []}}}',
        encoding="utf-8",
    )
    with pytest.raises(FixtureError, match="recorded"):
        load_fixture_file(recorded)


def test_unlabeled_json_is_refused(tmp_path: Path) -> None:
    unlabeled = tmp_path / "fixture_unlabeled.json"
    unlabeled.write_text('{"results": {"entities": []}}', encoding="utf-8")
    with pytest.raises(FixtureError, match="_meta"):
        load_fixture_file(unlabeled)


# ---------- normalizer: success path ----------


def test_synthetic_success_map_fields_into_records() -> None:
    records = _payload_records(SYNTHETIC_SUCCESS, intended_name="Mock Studio Notebooks")
    assert len(records) == 2

    first = records[0]
    assert first.qloo_entity_id == "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
    assert first.entity_name == "Mock Studio Notebooks"
    assert first.entity_subtype == "urn:entity:brand"
    assert first.popularity == 0.4242
    assert first.tags == ["urn:tag:keyword:mock:notebook", "urn:tag:keyword:mock:stationery"]
    assert first.coverage_status == "available"
    assert first.match_quality == "exact"
    assert first.fixture_mode is True
    assert first.source == "fixture"
    assert first.limitations == []

    second = records[1]
    # Second entity was not the intended search term, so partial match quality.
    assert second.match_quality == "partial"
    assert second.coverage_status == "available"


def test_normailized_record_has_stable_evidence_id() -> None:
    records_a = _payload_records(SYNTHETIC_SUCCESS, intended_name="Mock Studio Notebooks")
    records_b = _payload_records(SYNTHETIC_SUCCESS, intended_name="Mock Studio Notebooks")
    assert [r.evidence_id for r in records_a] == [r.evidence_id for r in records_b]


# ---------- normalizer: adversarial fixtures ----------


def test_missing_fields_yields_partial_and_ambiguous() -> None:
    records = _payload_records(ADV_MISSING, intended_name="Mock Gappy Brand")
    assert len(records) == 2

    first = records[0]
    assert first.coverage_status == "partial"
    assert first.popularity is None
    assert "documented field missing from entity payload: popularity" in first.limitations

    second = records[1]
    # No name and no entity_id at all: match is unconfirmable.
    assert second.coverage_status == "ambiguous"
    assert second.qloo_entity_id is None
    assert second.entity_name is None
    assert any("ENTITY_MATCH_AMBIGUOUS" in lim for lim in second.limitations)
    assert any("entity_id" in lim for lim in second.limitations)
    assert any("name" in lim for lim in second.limitations)


def test_empty_entities_is_missing_not_error() -> None:
    records = _payload_records(ADV_NO_MATCH)
    assert len(records) == 1
    rec = records[0]
    assert rec.error_code == "QLOO_NO_MATCH"
    assert rec.coverage_status == "missing"
    assert rec.match_quality == "none"
    assert rec.qloo_entity_id is None
    assert any("not a negative signal" in lim for lim in rec.limitations)


def test_malformed_response_yields_error_record() -> None:
    records = _payload_records(ADV_MALFORMED)
    assert len(records) == 1
    rec = records[0]
    assert rec.error_code == "QLOO_MALFORMED_RESPONSE"
    assert rec.coverage_status == "error"
    assert any("results" in lim for lim in rec.limitations)


def test_error_records_are_deterministic() -> None:
    a = _payload_records(ADV_NO_MATCH)
    b = _payload_records(ADV_NO_MATCH)
    assert a[0].evidence_id == b[0].evidence_id


# ---------- normalizer: direct payload edge cases ----------


def test_non_object_entities_entries_error_itemwise() -> None:
    raw = load_fixture_file(FIXTURES_DIR / SYNTHETIC_SUCCESS)
    raw["response"]["results"]["entities"].append("not-an-object")
    payload = QlooPayload(
        endpoint="search",
        query_params_redacted={"query": "x"},
        payload=raw["response"],
        source="fixture",
        fixture_mode=True,
    )
    records = normalize_response(payload)
    assert len(records) == 3
    assert any(
        r.error_code == "QLOO_MALFORMED_RESPONSE"
        and any("[2]" in lim for lim in r.limitations)
        for r in records
    )


def test_entities_not_a_list_is_malformed(tmp_path: Path) -> None:
    payload = QlooPayload(
        endpoint="search",
        query_params_redacted={},
        payload={"success": True, "results": {"entities": "oops"}},
        source="fixture",
        fixture_mode=True,
    )
    records = normalize_response(payload)
    assert len(records) == 1
    assert records[0].error_code == "QLOO_MALFORMED_RESPONSE"
    assert records[0].coverage_status == "error"


def test_missing_entities_key_is_malformed() -> None:
    payload = QlooPayload(
        endpoint="search",
        query_params_redacted={},
        payload={"success": True, "results": {}},
        source="fixture",
        fixture_mode=True,
    )
    records = normalize_response(payload)
    assert len(records) == 1
    assert records[0].error_code == "QLOO_MALFORMED_RESPONSE"
    assert any("results.entities" in lim for lim in records[0].limitations)


def test_popularity_outside_0_1_is_partial_not_value() -> None:
    payload = QlooPayload(
        endpoint="search",
        query_params_redacted={},
        payload={
            "success": True,
            "results": {
                "entities": [
                    {
                        "name": "Mock Out Of Range",
                        "entity_id": "99999999-AAAA-BBBB-CCCC-DDDDDDDDDDDD",
                        "subtype": "urn:entity:brand",
                        "properties": {"popularity": 1.5},
                        "tags": [],
                    }
                ]
            },
        },
        source="fixture",
        fixture_mode=True,
    )
    records = normalize_response(payload, intended_name="Mock Out Of Range")
    assert len(records) == 1
    rec = records[0]
    assert rec.popularity is None
    assert rec.coverage_status == "partial"
    assert any("0-1 range" in lim for lim in rec.limitations)


# ---------- FixtureSource.end-to-end ----------


def test_fixture_source_loads_synthetic_search() -> None:
    src = FixtureSource(FIXTURES_DIR)
    payload = src.load("search", {"query": "MOCK studio notebook"})
    assert payload.source == "fixture"
    assert payload.fixture_mode is True
    assert payload.payload["results"]["entities"]
