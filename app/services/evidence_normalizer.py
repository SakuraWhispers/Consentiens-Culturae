"""Evidence normalizer (docs/architecture.md section 2, Stage 1/2).

LIVE VERIFIED shapes (docs/qloo-api-notes.md section 3, G1 2026-10-16):
  /search:       {"results": [entity, ...]}  (list, NOT results.entities)
  /v2/insights:  {"success": bool, "results": {"entities": [...]}} (matches docs)
  /v2/tags:      {"success": bool, "results": {"tags": [...]}} — a tag lookup,
                 NOT evidence; the normalizer refuses it with a named error so a
                 tag list can never become an evidence record.
  entity fields: name, entity_id, popularity TOP-LEVEL 0–1 float (fallback:
                 properties.popularity), tags[] with id OR tag_id OR value,
                 subtype (fallback: types[0]), type. Unknown fields are skipped.
Missing documented fields reduce coverage to `partial` with the missing field
named in `limitations` — never silently dropped, never coerced to zero, never
fabricated (AGENTS.md hard rule 1).

This file changes when Qloo changes a field name; nothing else does.
"""

from __future__ import annotations

from typing import Any

from app.integrations.qloo_adapter import QlooPayload
from app.schemas.evidence import (
    ErrorCode,
    EvidenceRecord,
    MatchQuality,
    SourceKind,
    make_error_record,
    stable_evidence_id,
)

# Error-code literal values are checked against app.schemas.evidence.ErrorCode.


def _entity_from_result_entity(entity: dict[str, Any], intended_name: str | None) -> dict[str, Any]:
    """Extract ONLY documented fields from one entity object.

    Returns the normalized raw dict plus a list of coverage limitations.
    """
    entity_id = entity.get("entity_id")
    name = entity.get("name")
    subtype = entity.get("subtype")
    if not isinstance(subtype, str):
        # Live /search hits carry types[] (plural) with no subtype field.
        types_obj = entity.get("types")
        if isinstance(types_obj, list) and types_obj and isinstance(types_obj[0], str):
            subtype = types_obj[0]

    # Live VERIFIED: popularity is top-level; properties.popularity is fallback.
    popularity = entity.get("popularity")
    props_obj = entity.get("properties")
    props = props_obj if isinstance(props_obj, dict) else {}
    if popularity is None:
        popularity = props.get("popularity") if isinstance(props, dict) else None

    tags_obj = entity.get("tags")
    tag_list = tags_obj if isinstance(tags_obj, list) else []
    tag_ids: list[str] = []
    malformed_tags = False
    for tag in tag_list:
        # Live VERIFIED: tags carry tag_id/value; older docs said id. Accept all.
        if isinstance(tag, dict):
            for key in ("id", "tag_id", "value"):
                val = tag.get(key)
                if isinstance(val, str):
                    tag_ids.append(val)
                    break
            else:
                malformed_tags = True
        else:
            malformed_tags = True

    limitations: list[str] = []

    if entity_id is None:
        limitations.append("documented field missing from entity payload: entity_id")
    if name is None:
        limitations.append("documented field missing from entity payload: name")
    if not isinstance(props, dict):
        limitations.append("documented field missing/malformed from entity payload: properties")
    if popularity is None:
        limitations.append("documented field missing from entity payload: popularity")
    elif isinstance(popularity, bool) or not isinstance(popularity, (int, float)):
        limitations.append("popularity was not a number")
        popularity = None
    elif not (0.0 <= float(popularity) <= 1.0):
        limitations.append(f"popularity outside documented 0-1 range: {popularity}")
        popularity = None
    if malformed_tags:
        limitations.append("malformed tag entries ignored (documented shape: tags[].id as string)")

    match_quality, is_exact = _match_quality(intended_name, entity_id, name)
    coverage_status = _coverage_status(match_quality, popularity, tag_ids, limitations)
    if match_quality == "ambiguous":
        limitations.append(
            "ENTITY_MATCH_AMBIGUOUS: cannot confirm this entity is the one intended"
        )

    return {
        "qloo_entity_id": entity_id if isinstance(entity_id, str) else None,
        "entity_name": name if isinstance(name, str) else None,
        "entity_subtype": subtype if isinstance(subtype, str) else None,
        "popularity": float(popularity) if popularity is not None else None,
        "tag_ids": tag_ids,
        "match_quality": match_quality,
        "coverage_status": coverage_status,
        "limitations": limitations,
        "is_exact": is_exact,
    }


def _match_quality(
    intended_name: str | None,
    entity_id: object,
    name: object,
) -> tuple[MatchQuality, bool]:
    """Match quality against the concept/brief term that triggered retrieval.

    exact:   names match case-insensitively (string comparison only)
    partial: a different name came back (could still be a real variant)
    ambiguous: no name at all — entity identity cannot be confirmed
    """
    if not isinstance(name, str) or not name.strip():
        return "ambiguous", False
    if intended_name is None:
        # Term not given by caller: we can only observe a name exists.
        return "partial", False
    if name.strip().lower() == intended_name.strip().lower():
        return "exact", True
    return "partial", False


def _coverage_status(
    match_quality: MatchQuality,
    popularity: float | None,
    tag_ids: list[str],
    limitations: list[str],
) -> str:
    """Worst case wins: ambiguous beats missing beats partial beats available.

    - match ambiguous             -> ambiguous
    - any documented limit present -> partial (or ambiguous, above)
    - nothing documented missing   -> available
    Error codes never arise here: they arrive only through make_error_record.
    """
    if match_quality == "ambiguous":
        return "ambiguous"
    if limitations or popularity is None:
        return "partial"
    return "available"


def normalize_response(
    payload: QlooPayload,
    intended_name: str | None = None,
) -> list[EvidenceRecord]:
    """Map one retrieval response into normalized EvidenceRecords.

    Accepted top-level shapes (all LIVE VERIFIED 2026-10-16):
      - {"results": [...]}                  — /search (list of entities)
      - {"results": {"entities": [...]}}     — /v2/insights (also old synthetics)
    A {"results": {"tags": [...]}} tag-lookup response is refused with
    QLOO_MALFORMED_RESPONSE: tag lists are retrieval-planning input, never
    evidence records.

    Error mapping (docs/qloo-api-notes.md section 5):
      - no "results" object, no entities list, entity not an object
        -> QLOO_MALFORMED_RESPONSE
      - empty entities list -> QLOO_NO_MATCH, coverage_status="missing"
    """
    endpoint = payload.endpoint
    params = dict(payload.query_params_redacted)
    source_kind = payload.source
    fixture_mode = payload.fixture_mode
    body = payload.payload

    def error(
        code: ErrorCode,
        limitations: list[str] | None = None,
    ) -> list[EvidenceRecord]:
        return [
            make_error_record(
                endpoint_or_operation=endpoint,
                query_params_redacted=params,
                error_code=code,
                source=source_kind,  # type: ignore[arg-type]
                fixture_mode=fixture_mode,
                limitations=limitations,
            )
        ]

    if not isinstance(body, dict):
        return error("QLOO_MALFORMED_RESPONSE", ["response body was not an object"])

    results = body.get("results")
    if isinstance(results, list):
        # Live /search shape: results IS the entity list.
        entities: Any = results
        list_label = "results"
    elif isinstance(results, dict):
        if "tags" in results and "entities" not in results:
            return error(
                "QLOO_MALFORMED_RESPONSE",
                ["tags lookup response has no entities: results.tags is not evidence; resolve tag IDs then call insights"],
            )
        if "entities" not in results:
            return error(
                "QLOO_MALFORMED_RESPONSE",
                ["expected key missing from response: results.entities"],
            )
        entities = results["entities"]
        list_label = "results.entities"
    else:
        return error("QLOO_MALFORMED_RESPONSE", ["expected key missing from response: results"])

    if entities == []:
        return error(
            "QLOO_NO_MATCH",
            [
                "documented empty results.entities: no match, not a negative signal"
            ],
        )
    if not isinstance(entities, list):
        return error(
            "QLOO_MALFORMED_RESPONSE",
            [f"{list_label} was not a list"],
        )

    records: list[EvidenceRecord] = []
    for index, entity in enumerate(entities):
        if not isinstance(entity, dict):
            records.extend(
                error(
                    "QLOO_MALFORMED_RESPONSE",
                    [f"{list_label}[{index}] was not an object"],
                )
            )
            continue
        extracted = _entity_from_result_entity(entity, intended_name)
        records.append(
            EvidenceRecord(
                evidence_id=stable_evidence_id(
                    endpoint_or_operation=endpoint,
                    query_params_redacted=params,
                    qloo_entity_id=extracted["qloo_entity_id"],
                ),
                source=source_kind,  # type: ignore[arg-type]
                fixture_mode=fixture_mode,
                endpoint_or_operation=endpoint,
                query_params_redacted=params,
                qloo_entity_id=extracted["qloo_entity_id"],
                entity_name=extracted["entity_name"],
                entity_subtype=extracted["entity_subtype"],
                popularity=extracted["popularity"],
                tags=extracted["tag_ids"],
                match_quality=extracted["match_quality"],
                coverage_status=extracted["coverage_status"],  # type: ignore[arg-type]
                limitations=extracted["limitations"],
                raw={
                    k: extracted[k]
                    for k in (
                        "qloo_entity_id",
                        "entity_name",
                        "entity_subtype",
                        "popularity",
                        "tag_ids",
                    )
                },
            )
        )
    return records


__all__ = ["normalize_response"]
