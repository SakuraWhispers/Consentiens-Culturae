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


# --- Wave-1 item 9 (owner-app 2026-10-26): quote-grounding enforcement ---
# "stated" means the words come from the USER'S OWN concept entry
# (name / description / attribute keys+values). A quote that is not
# verbatim in that text is demoted: quote dropped, basis -> inferred, and
# a rejected note names why. An invented quote must never reach the UI
# dressed as the user's speech.


def _texts(cid: str = "A"):
    # same flat-string shape suggest_attributes_llm builds from a concept
    description = (
        "A small Berlin studio making recycled-paper notebooks with vegetable-oil"
        " inks. Quality over volume, slow production, and repairable bindings."
    )
    return {
        cid: [
            "Ayer Studio",
            description,
            "material: recycled covers",
            "recycled covers",
        ]
    }


def test_verbatim_quote_is_kept_as_stated() -> None:
    kept, rejected = sanitize_suggestions(
        [{
            "concept_id": "A",
            "attributes": [{
                "attribute": "material", "value": "recycled",
                "basis": "stated", "quote": "recycled-paper notebooks",
            }],
        }],
        {"A"},
        concept_texts=_texts(),
    )
    assert not rejected
    assert kept[0]["attributes"][0] == {
        "attribute": "material", "value": "recycled",
        "basis": "stated", "quote": "recycled-paper notebooks",
    }


def test_quote_matches_ignoring_case() -> None:
    kept, rejected = sanitize_suggestions(
        [{
            "concept_id": "A",
            "attributes": [{
                "attribute": "positioning", "value": "quality",
                "basis": "stated", "quote": "QUALITY OVER VOLUME",
            }],
        }],
        {"A"},
        concept_texts=_texts(),
    )
    assert not rejected
    assert kept[0]["attributes"][0]["basis"] == "stated"


def test_non_verbatim_quote_is_demoted_with_a_note() -> None:
    kept, rejected = sanitize_suggestions(
        [{
            "concept_id": "A",
            "attributes": [{
                "attribute": "material", "value": "bamboo",
                "basis": "stated", "quote": "bamboo cores, hand-finished in Kyoto",
            }],
        }],
        {"A"},
        concept_texts=_texts(),
    )
    assert len(rejected) == 1 and "not verbatim" in rejected[0]
    assert kept[0]["attributes"][0] == {
        "attribute": "material", "value": "bamboo",
        "basis": "inferred", "quote": "",
    }


def test_stated_without_a_quote_is_demoted() -> None:
    kept, rejected = sanitize_suggestions(
        [{
            "concept_id": "A",
            "attributes": [
                {"attribute": "material", "value": "recycled", "basis": "stated"},
                {"attribute": "mood", "value": "calm", "basis": "stated", "quote": "   "},
            ],
        }],
        {"A"},
        concept_texts=_texts(),
    )
    assert len(rejected) == 2
    assert all(a["basis"] == "inferred" and a["quote"] == "" for a in kept[0]["attributes"])


def test_long_verbatim_quote_passes_then_gets_capped() -> None:
    long_quote = (
        "A small Berlin studio making recycled-paper notebooks with"
        " vegetable-oil inks. Quality over volume, slow production, and repairable"
    )
    kept, rejected = sanitize_suggestions(
        [{
            "concept_id": "A",
            "attributes": [{
                "attribute": "positioning", "value": "small studio",
                "basis": "stated", "quote": long_quote,
            }],
        }],
        {"A"},
        concept_texts=_texts(),
    )
    assert not rejected
    a = kept[0]["attributes"][0]
    assert a["basis"] == "stated"
    assert len(a["quote"]) <= 120


def test_legitimate_quote_from_an_attribute_value_is_verbatim() -> None:
    kept, rejected = sanitize_suggestions(
        [{
            "concept_id": "A",
            "attributes": [{
                "attribute": "material", "value": "recycled covers",
                "basis": "stated", "quote": "recycled covers",
            }],
        }],
        {"A"},
        concept_texts=_texts(),
    )
    assert not rejected
    assert kept[0]["attributes"][0]["basis"] == "stated"


def test_llm_level_wiring_passes_the_concept_texts() -> None:
    """suggest_attributes_llm builds concept_texts from the request's own
    concepts, so the sanitizer can verify quotes against them."""
    import app.agents.analyst as analyst_mod
    from app.agents.analyst import suggest_attributes_llm

    captured: dict = {}

    def fake_complete_json(api_key, model, system, payload, *a, **kw):
        captured["api"] = True
        return {"suggestions": [{
            "concept_id": "A",
            "attributes": [{
                "attribute": "material", "value": "bamboo",
                "basis": "stated", "quote": "bamboo cores",
            }],
        }]}

    orig = analyst_mod.complete_json
    analyst_mod.complete_json = fake_complete_json  # type: ignore[assignment]
    try:
        kept, rejected = suggest_attributes_llm(
            "k", "m",
            [{"concept_id": "A", "name": "Ayer Studio",
              "description": "Recycled-paper notebooks.", "attributes": {}}],
        )
    finally:
        analyst_mod.complete_json = orig  # type: ignore[assignment]
    assert captured["api"]
    assert rejected and "not verbatim" in rejected[0]
    assert kept[0]["attributes"][0]["basis"] == "inferred"
