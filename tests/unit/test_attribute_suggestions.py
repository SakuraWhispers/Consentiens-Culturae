"""Unit tests for the attribute-suggester output sanitizer (2026-10-23)."""

from app.agents.analyst import sanitize_suggestions


def test_keeps_grounded_proposals_and_normalizes_basis() -> None:
    kept, rejected = sanitize_suggestions(
        [
            {
                "concept_id": "A",
                "attributes": [
                    {"attribute": "material", "value": "recycled", "basis": "STATED", "quote": "recycled covers"},
                    {"attribute": "price_band", "value": "under-25"},
                ],
            }
        ],
        {"A"},
    )
    assert not rejected
    assert kept == [
        {
            "concept_id": "A",
            "attributes": [
                {"attribute": "material", "value": "recycled", "basis": "stated", "quote": "recycled covers"},
                {"attribute": "price_band", "value": "under-25", "basis": "inferred", "quote": ""},
            ],
        }
    ]


def test_drops_unknown_concepts_and_empty_fields() -> None:
    kept, rejected = sanitize_suggestions(
        [
            {"concept_id": "Z", "attributes": [{"attribute": "material", "value": "recycled"}]},
            {"concept_id": "A", "attributes": [{"attribute": "", "value": "recycled"}]},
            {"concept_id": "A", "attributes": []},
            "not-an-object",
            {"concept_id": "A", "attributes": [{"attribute": "material", "value": "recycled"}]},
        ],
        {"A"},
    )
    assert len(kept) == 1 and kept[0]["attributes"][0]["attribute"] == "material"
    assert len(rejected) == 4


def test_target_filter_and_cap() -> None:
    kept, rejected = sanitize_suggestions(
        [
            {
                "concept_id": "A",
                "attributes": [
                    {"attribute": "material", "value": "recycled"},
                    {"attribute": "mood", "value": "calm"},
                ],
            }
        ],
        {"A"},
        target_attributes={"material"},
    )
    assert kept[0]["attributes"][0]["attribute"] == "material"
    assert any("not requested" in note for note in rejected)


def test_non_list_payload_is_rejected_cleanly() -> None:
    kept, rejected = sanitize_suggestions({"suggestions": []}, {"A"})
    assert kept == []
    assert rejected == ["suggestion payload was not a list"]
