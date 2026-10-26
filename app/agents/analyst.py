"""Analyst + critic wrappers (G3): prompt, call, schema-validate.

Validation failures raise (pydantic ValidationError or AgentLLMError); the
coordinator retries once, then falls back to the deterministic template.

Resilience rules added after the 2026-10-20 live run (c2b65018…):

* Transport-shape normalization: a param named "filter" is renamed to the
  documented "filter.type" (flat string or nested object), so a model that
  means the right thing is not rejected for its shape.
* Synonym bridges for closed enums the model words differently (critic
  severity "medium" -> "minor", lowercase issue codes, action synonyms).
* Per-item salvage: one invalid claim or finding is dropped and REPORTED;
  the rest of the output survives. Only an output where nothing survives
  raises, so the coordinator still retries and falls back.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.agents.llm_client import DEFAULT_LLM_BASE_URL, complete_json
from app.agents.prompts import (
    ANALYST_SYSTEM,
    ATTRIBUTE_SUGGESTER_SYSTEM,
    CONCEPT_CRITIC_SYSTEM,
    CRITIC_SYSTEM,
    RESEARCHER_SYSTEM,
    REPORTER_SYSTEM,
    REVISION_SYSTEM,
    TIEBREAK_SYSTEM,
)
from app.agents.researcher import PlanRejectedError, salvage_calls
from app.agents.schemas import (
    AnalysisDraft,
    CriticFindingModel,
    CriticOutput,
    RetrievalPlan,
    RichClaim,
)

RAW_HEAD_LIMIT = 600

# A repair attempt re-sends the same prompt with the validation error attached.
# Temperature 0 would reproduce the identical (invalid) answer, so the repair
# attempt samples slightly instead of repeating itself.
REPAIR_TEMPERATURE = 0.3


def _with_hint(payload: dict[str, Any], hint: str | None) -> dict[str, Any]:
    """Attach the code's rejection reason so the model can correct itself."""
    if not hint:
        return payload
    return {**payload, "previous_output_rejected": hint}


def _raw_head(parsed: dict[str, Any]) -> str:
    """Truncated copy of the model payload for diagnosis (never secrets)."""
    import json

    try:
        return json.dumps(parsed)[:RAW_HEAD_LIMIT]
    except (TypeError, ValueError):
        return ""


def _as_param_value(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _normalize_plan_params(endpoint: str, params: dict[str, Any]) -> dict[str, str]:
    """Transport-shape normalization for planned-call params (invents nothing).

    Live finding (2026-10-20): the researcher wrote a param literally named
    "filter" (flat string or nested object) instead of the documented
    "filter.type"; the allowlist then rejected the WHOLE plan, including the
    good search calls. This renames the known shapes into the allowlisted key
    names only: a filter.type that is not the docs-verified urn still fails
    the researcher rules, and an unknown key is still rejected downstream.
    """
    out: dict[str, str] = {}
    for key, value in params.items():
        if endpoint == "search" and key == "q":
            out["query"] = _as_param_value(value)
            continue
        if key == "filter":
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if sub_key == "type":
                        out["filter.type"] = _as_param_value(sub_value)
                    elif sub_key == "tags":
                        out["filter.tags"] = _as_param_value(sub_value)
                continue
            out["filter.type"] = _as_param_value(value)
            continue
        if endpoint == "insights" and key == "type":
            out["filter.type"] = _as_param_value(value)
            continue
        if endpoint == "insights" and key == "tags":
            out["filter.tags"] = _as_param_value(value)
            continue
        out[key] = _as_param_value(value)
    return out


def _normalize_calls(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize the planned-call list into (endpoint, params) dicts."""
    calls: list[dict[str, Any]] = []
    raw_calls = parsed.get("calls", [])
    if not isinstance(raw_calls, list):
        return calls
    for call in raw_calls:
        if not isinstance(call, dict):
            continue
        endpoint = str(call.get("endpoint", ""))
        params = call.get("params")
        if not isinstance(params, dict):
            params = {}
        calls.append({"endpoint": endpoint, "params": _normalize_plan_params(endpoint, params)})
    return calls


def draft_plan_llm(
    api_key: str, model: str, concept_names: list[str], category_hint: str | None,
    timeout: float = 30.0, client: httpx.Client | None = None,
    base_url: str = DEFAULT_LLM_BASE_URL,
    max_tokens: int | None = None, reasoning: dict[str, Any] | None = None,
    repair_hint: str | None = None,
) -> RetrievalPlan:
    parsed = complete_json(
        api_key, model, RESEARCHER_SYSTEM,
        _with_hint(
            {"concepts": concept_names, "category_hint": category_hint, "max_calls": 10},
            repair_hint,
        ),
        timeout, client, base_url, max_tokens, reasoning,
        top_level_list_key="calls",
        temperature=REPAIR_TEMPERATURE if repair_hint else 0.0,
    )
    kept, rejected = salvage_calls(_normalize_calls(parsed))
    if not kept:
        raise PlanRejectedError(
            rejected[0] if rejected else "researcher plan contained no usable calls"
        )
    # The researcher selects the category (2026-10-24). A URN-shaped "category"
    # is not a category - refuse it rather than resolving an invented id.
    raw_category = parsed.get("category")
    category: str | None = None
    if isinstance(raw_category, str):
        category = raw_category.strip()[:120] or None
        if category and category.lower().startswith("urn:"):
            category = None
            rejected = list(rejected) + ["model wrote a 'urn:' category; ignored (invented identifier)"]
    return RetrievalPlan(
        calls=[{"endpoint": c["endpoint"], "params": c["params"]} for c in kept],
        rejected=rejected,
        raw_head=_raw_head(parsed),
        category=category,
    )


def _bridge_claim_synonyms(parsed: dict[str, Any]) -> dict[str, Any]:
    """Transport-side synonym bridge for claim envelope values.

    Live finding: models sometimes write strength:"medium" (confidence's value
    bleeding into strength). The ONLY unambiguous mapping is medium→moderate;
    it is applied here so the strict pydantic schema judges CONTENT, not one
    collateral word. All other values stay strict.
    """
    claims = parsed.get("claims", [])
    if isinstance(claims, list):
        for claim in claims:
            if isinstance(claim, dict) and claim.get("strength") == "medium":
                claim["strength"] = "moderate"
    return parsed


# Closed-enum synonyms for the critic's envelope fields. "medium" has no
# counterpart in major|minor|info, so the nearest rung (minor) is used; every
# other value stays strict and the item is dropped if it does not fit.
_CRITIC_SEVERITY_SYNONYMS = {
    "medium": "minor",
    "moderate": "minor",
    "med": "minor",
    "normal": "minor",
    "high": "major",
    "critical": "major",
    "severe": "major",
    "blocker": "major",
    "fatal": "major",
    "low": "info",
    "note": "info",
    "informational": "info",
    "information": "info",
    "trivial": "info",
    "hint": "info",
}

_CRITIC_ACTION_SYNONYMS = {
    "delete": "remove",
    "drop": "remove",
    "reject": "remove",
    "remove_claim": "remove",
    "reword": "revise_wording",
    "rephrase": "revise_wording",
    "revise": "revise_wording",
    "rewrite": "revise_wording",
    "edit": "revise_wording",
    "reword_wording": "revise_wording",
    "weaken": "qualify",
    "hedge": "qualify",
    "caveat": "qualify",
    "add_caveat": "qualify",
    "soften": "qualify",
}


def _bridge_critic_synonyms(parsed: dict[str, Any]) -> dict[str, Any]:
    """Transport-side synonym bridge for critic envelope values.

    Live finding (2026-10-20, run c2b65018…): the model wrote severity
    "medium", which is not in the closed enum major|minor|info, and the whole
    critique was thrown away. The nearest allowed value is applied here so the
    schema judges the CONTENT of the finding, not one collateral word. Values
    with no unambiguous counterpart stay strict and the item is dropped (and
    reported) by the caller.
    """
    findings = parsed.get("findings", [])
    if isinstance(findings, list):
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            severity = finding.get("severity")
            if isinstance(severity, str):
                finding["severity"] = _CRITIC_SEVERITY_SYNONYMS.get(
                    severity.strip().lower(), severity
                )
            code = finding.get("issue_code")
            if isinstance(code, str):
                finding["issue_code"] = (
                    code.strip().upper().replace(" ", "_").replace("-", "_")
                )
            action = finding.get("suggested_action")
            if isinstance(action, str):
                finding["suggested_action"] = _CRITIC_ACTION_SYNONYMS.get(
                    action.strip().lower().replace(" ", "_"), action
                )
    return parsed


def _first_validation_error(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "invalid output"
    err = errors[0]
    loc = ".".join(str(part) for part in err.get("loc", ()))
    msg = str(err.get("msg", "invalid"))
    value = err.get("input", None)
    detail = f"{loc}: {msg}" if loc else msg
    if value is not None:
        detail += f" (got {value!r})"
    return detail


def _salvage_items(
    raw_items: Any, model: type[BaseModel], label: str
) -> tuple[list[dict[str, Any]], list[str], Exception | None]:
    """Validate items one by one: keep the valid ones, report the rejected.

    Returns (kept, rejection_notes, first_error). `first_error` is the
    original ValidationError of the first bad item, so a caller that ends up
    with nothing can re-raise it (the coordinator then retries and falls
    back exactly as before).
    """
    kept: list[dict[str, Any]] = []
    rejected: list[str] = []
    first_error: Exception | None = None
    items = raw_items if isinstance(raw_items, list) else []
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            rejected.append(f"{label}[{index}]: not a JSON object")
            continue
        try:
            obj = model(**raw)
        except ValidationError as exc:
            rejected.append(f"{label}[{index}]: {_first_validation_error(exc)}")
            if first_error is None:
                first_error = exc
            continue
        kept.append(obj.model_dump())
    return kept, rejected, first_error


def draft_claims_llm(
    api_key: str, model: str, score_summary: dict[str, Any],
    evidence_summary: dict[str, Any], limitations: list[str], weights: dict[str, float],
    timeout: float = 30.0, client: httpx.Client | None = None,
    base_url: str = DEFAULT_LLM_BASE_URL,
    max_tokens: int | None = None, reasoning: dict[str, Any] | None = None,
    repair_hint: str | None = None,
) -> AnalysisDraft:
    parsed = complete_json(
        api_key, model, ANALYST_SYSTEM,
        _with_hint(
            {"scores": score_summary, "evidence": evidence_summary,
             "limitations": limitations, "weights": weights},
            repair_hint,
        ),
        timeout, client, base_url, max_tokens, reasoning,
        top_level_list_key="claims",
        temperature=REPAIR_TEMPERATURE if repair_hint else 0.0,
    )
    parsed = _bridge_claim_synonyms(parsed)
    claims, rejected, first_error = _salvage_items(
        parsed.get("claims", []), RichClaim, "claims"
    )
    if not claims:
        if first_error is not None:
            raise first_error
        raise ValueError("analyst returned no claims")
    return AnalysisDraft(claims=claims, rejected=rejected, raw_head=_raw_head(parsed))


def review_claims_llm(
    api_key: str, model: str, claims: list[dict[str, Any]],
    score_summary: dict[str, Any], evidence_ids: list[str],
    timeout: float = 30.0, client: httpx.Client | None = None,
    base_url: str = DEFAULT_LLM_BASE_URL,
    max_tokens: int | None = None, reasoning: dict[str, Any] | None = None,
    repair_hint: str | None = None,
    evidence_by_concept: dict[str, list[str]] | None = None,
) -> CriticOutput:
    payload: dict[str, Any] = {
        "claims": claims, "scores": score_summary, "known_evidence_ids": evidence_ids,
    }
    if evidence_by_concept is not None:
        # Wave-1 item 6: per-concept evidence map alongside the flat list.
        # The flat list stays for aggregate claims and backward compatibility.
        payload["known_evidence_by_concept"] = evidence_by_concept
    parsed = complete_json(
        api_key, model, CRITIC_SYSTEM,
        _with_hint(payload, repair_hint),
        timeout, client, base_url, max_tokens, reasoning,
        top_level_list_key="findings",
        temperature=REPAIR_TEMPERATURE if repair_hint else 0.0,
    )
    parsed = _bridge_critic_synonyms(parsed)
    findings, rejected, first_error = _salvage_items(
        parsed.get("findings", []), CriticFindingModel, "findings"
    )
    if not findings and first_error is not None:
        raise first_error
    # An empty findings list is a legitimate "no issues" outcome.
    return CriticOutput(findings=findings, rejected=rejected, raw_head=_raw_head(parsed))


def revise_claims_llm(
    api_key: str, model: str, claims: list[dict[str, Any]], findings: list[dict[str, Any]],
    timeout: float = 30.0, client: httpx.Client | None = None,
    base_url: str = DEFAULT_LLM_BASE_URL,
    max_tokens: int | None = None, reasoning: dict[str, Any] | None = None,
    repair_hint: str | None = None,
) -> AnalysisDraft:
    parsed = complete_json(
        api_key, model, REVISION_SYSTEM,
        _with_hint({"claims": claims, "findings": findings}, repair_hint),
        timeout, client, base_url, max_tokens, reasoning,
        top_level_list_key="claims",
        temperature=REPAIR_TEMPERATURE if repair_hint else 0.0,
    )
    parsed = _bridge_claim_synonyms(parsed)
    claims_out, rejected, first_error = _salvage_items(
        parsed.get("claims", []), RichClaim, "claims"
    )
    if not claims_out:
        if first_error is not None:
            raise first_error
        raise ValueError("revision returned no claims")
    return AnalysisDraft(
        claims=claims_out, rejected=rejected, raw_head=_raw_head(parsed)
    )


def compare_tied_llm(
    api_key: str, model: str, tied: list[dict[str, Any]], evidence_summary: dict[str, Any],
    weights: dict[str, float], before: dict[str, float], after: dict[str, float],
    timeout: float = 30.0, client: httpx.Client | None = None,
    base_url: str = DEFAULT_LLM_BASE_URL,
    max_tokens: int | None = None, reasoning: dict[str, Any] | None = None,
    repair_hint: str | None = None,
) -> AnalysisDraft:
    """The tie-break comparison (2026-10-22): a focused run on the concepts
    that the deterministic scoring left level.

    Same rules as the analyst - it may not write a number that is not in the
    payload, and it may only cite evidence IDs that exist.
    """
    parsed = complete_json(
        api_key, model, TIEBREAK_SYSTEM,
        _with_hint(
            {
                "tied_concepts": tied,
                "evidence": evidence_summary,
                "weights": weights,
                "totals_before_tiebreak": before,
                "totals_after_tiebreak": after,
            },
            repair_hint,
        ),
        timeout, client, base_url, max_tokens, reasoning,
        top_level_list_key="claims",
        temperature=REPAIR_TEMPERATURE if repair_hint else 0.0,
    )
    parsed = _bridge_claim_synonyms(parsed)
    claims, rejected, first_error = _salvage_items(
        parsed.get("claims", []), RichClaim, "claims"
    )
    if not claims:
        if first_error is not None:
            raise first_error
        raise ValueError("tie-break comparison returned no claims")
    return AnalysisDraft(claims=claims, rejected=rejected, raw_head=_raw_head(parsed))


def sanitize_suggestions(
    raw: Any,
    known_concept_ids: set[str],
    target_attributes: set[str] | None = None,
    concept_texts: dict[str, list[str]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate the suggester's output, cutting silently the unsalvageable.

    Returns (kept, rejected_notes). Kept items: {"concept_id", "attributes":
    [{"attribute", "value", "basis", "quote"}]}. The suggester never writes
    into the brief: the user decides what (if anything) to copy.

    Wave-1 item 9 (owner-app 2026-10-26): when concept_texts is supplied
    (concept_id -> the user's own texts for that concept), a "stated" basis
    must quote that text VERBATIM. A non-verbatim or missing quote is demoted
    to inferred with the quote dropped — the suggester never launders an
    invented quote into the user's speech. Callers that pass no texts keep
    the legacy (unverified) behavior.
    """
    kept: list[dict[str, Any]] = []
    rejected: list[str] = []
    if not isinstance(raw, list):
        return [], ["suggestion payload was not a list"]
    for entry in raw:
        if not isinstance(entry, dict):
            rejected.append("suggestion entry was not an object")
            continue
        concept_id = str(entry.get("concept_id") or "").strip()
        if concept_id not in known_concept_ids:
            rejected.append(f"unknown concept_id {concept_id[:40]!r}")
            continue
        attrs_raw = entry.get("attributes")
        if not isinstance(attrs_raw, list) or not attrs_raw:
            rejected.append(f"{concept_id}: no attribute proposals")
            continue
        attrs: list[dict[str, Any]] = []
        own_texts = (concept_texts or {}).get(concept_id, [])
        for a in attrs_raw[:8]:
            if not isinstance(a, dict):
                rejected.append(f"{concept_id}: attribute entry was not an object")
                continue
            attribute = str(a.get("attribute") or "").strip()[:40]
            value = str(a.get("value") or "").strip()[:100]
            if not attribute or not value:
                rejected.append(f"{concept_id}: empty attribute or value")
                continue
            if target_attributes and attribute not in target_attributes:
                rejected.append(f"{concept_id}: attribute {attribute!r} is not requested")
                continue
            basis_raw = str(a.get("basis") or "inferred").strip().lower()
            basis = basis_raw if basis_raw in ("stated", "inferred") else "inferred"
            quote_raw = str(a.get("quote") or "").strip()
            # Verify BEFORE the 120-char cap: a truncated quote is no longer
            # verbatim and a good long quote must not fail on the cap.
            if basis == "stated" and concept_texts is not None:
                quote_low = quote_raw.lower()
                verbatim = bool(quote_low) and any(
                    quote_low in (t or "").lower() for t in own_texts
                )
                if not verbatim:
                    rejected.append(
                        f"{concept_id}: quote not verbatim in the concept's own text; demoted to inferred"
                    )
                    basis = "inferred"
                    quote_raw = ""
            quote = quote_raw[:120]
            attrs.append({"attribute": attribute, "value": value, "basis": basis, "quote": quote})
        if attrs:
            kept.append({"concept_id": concept_id, "attributes": attrs})
    return kept, rejected


def suggest_attributes_llm(
    api_key: str,
    model: str,
    concepts: list[dict[str, Any]],
    target_attributes: list[str] | None = None,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
    base_url: str = DEFAULT_LLM_BASE_URL,
    max_tokens: int | None = None,
    reasoning: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The cheap attribute suggester (2026-10-23): proposes grounded attribute
    values the user may copy into the form. Raises on a fully unusable answer
    (the route maps that to a plain error; nothing is auto-applied)."""
    payload: dict[str, Any] = {"concepts": concepts}
    if target_attributes:
        payload["requested_attribute_keys"] = sorted(target_attributes)
    parsed = complete_json(
        api_key,
        model,
        ATTRIBUTE_SUGGESTER_SYSTEM,
        payload,
        timeout,
        client,
        base_url,
        max_tokens,
        reasoning,
        temperature=0.0,
    )
    raw = parsed.get("suggestions")
    if not isinstance(raw, list):
        raise ValueError("suggester output had no suggestions list")
    # Wave-1 item 9: the user's OWN texts are what a "stated" quote may
    # echo — name, description, and the attribute keys/values they typed.
    own_texts = {
        str(c.get("concept_id")): [
            str(c.get("name") or ""),
            str(c.get("description") or ""),
            *(f"{k}: {v}" for k, v in (c.get("attributes") or {}).items()),
            *(str(v) for v in (c.get("attributes") or {}).values()),
        ]
        for c in concepts
    }
    kept, rejected = sanitize_suggestions(
        raw, {str(c.get("concept_id")) for c in concepts}, set(target_attributes or []),
        concept_texts=own_texts,
    )
    return kept, rejected


def strip_prose_fence(prose: str) -> str:
    """Shed a fenced wrapper (```...```) the model may add around prose.

    One shared implementation: the analyst wrapper strips the fence of its
    own report, and the coordinator applies the same strip to whatever the
    reporter hook returns (audit 2026-10-23 - the strip logic used to exist
    as two separate copies). Co-facing with prose, not with JSON payloads
    (the JSON-transport fence handling lives in llm_client).
    """
    prose = prose.strip()
    if prose.startswith("```"):
        prose = prose.split("\n", 1)[-1]
    if prose.endswith("```"):
        prose = prose.rsplit("```", 1)[0]
    return prose.strip()


def draft_report_llm(
    api_key: str,
    model: str,
    payload: dict[str, Any],
    timeout: float = 30.0,
    client: httpx.Client | None = None,
    base_url: str = DEFAULT_LLM_BASE_URL,
    max_tokens: int | None = None,
    reasoning: dict[str, Any] | None = None,
    repair_hint: str | None = None,
) -> str:
    """The verbose report (2026-10-22, Batch 3): prose, written only from the
    computed payload. The coordinator's number guard judges it afterwards."""
    parsed = complete_json(
        api_key, model, REPORTER_SYSTEM, _with_hint(payload, repair_hint),
        timeout, client, base_url, max_tokens, reasoning,
        temperature=REPAIR_TEMPERATURE if repair_hint else 0.0,
    )
    prose = parsed.get("report")
    if not isinstance(prose, str) or not prose.strip():
        raise ValueError("reporter output carried no prose")
    prose = strip_prose_fence(prose)
    if not prose:
        raise ValueError("reporter output was only a fence")
    return prose


def draft_concept_notes_llm(
    api_key: str,
    model: str,
    payload: dict[str, Any],
    timeout: float = 30.0,
    client: httpx.Client | None = None,
    base_url: str = DEFAULT_LLM_BASE_URL,
    max_tokens: int | None = None,
    reasoning: dict[str, Any] | None = None,
    repair_hint: str | None = None,
) -> dict[str, Any]:
    """The per-concept critique notes (2026-10-24): drawbacks per concept
    plus a short winning-concept note. The coordinator validates the ids,
    caps the lengths and runs the same number guard as the reporter."""
    parsed = complete_json(
        api_key, model, CONCEPT_CRITIC_SYSTEM, _with_hint(payload, repair_hint),
        timeout, client, base_url, max_tokens, reasoning,
        temperature=REPAIR_TEMPERATURE if repair_hint else 0.0,
    )
    notes = parsed.get("notes")
    if not isinstance(notes, dict) or not notes:
        raise ValueError("concept critic output carried no notes")
    winner_note = parsed.get("winner_note")
    if not isinstance(winner_note, str) or not winner_note.strip():
        raise ValueError("concept critic output carried no winner note")
    return {
        "notes": {cid: strip_prose_fence(str(text)) for cid, text in notes.items()},
        "winner_note": strip_prose_fence(winner_note),
    }


__all__ = [
    "draft_plan_llm",
    "draft_claims_llm",
    "review_claims_llm",
    "revise_claims_llm",
    "compare_tied_llm",
    "draft_report_llm",
    "draft_concept_notes_llm",
    "suggest_attributes_llm",
    "sanitize_suggestions",
]
