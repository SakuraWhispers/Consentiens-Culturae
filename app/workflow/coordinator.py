"""Deterministic coordinator (docs/architecture.md sections 2 and 4).

The only component that moves a run between states, and only through the
transition table. G2 path: brief -> retrieval plan -> evidence -> normalize ->
extract -> score -> template explanation -> deterministic critic -> validate ->
report. LLM stages use deterministic fallbacks (template + rule checks) until
G3 wires the analyst/critic behind a flag. Sensitivity is deferred to G4 and
recorded as a limitation. Code only: no LLM call, no randomness.
"""

from __future__ import annotations

import re
import time
from typing import Any

from sqlalchemy.engine import Engine

from app.agents.analyst import strip_prose_fence
from app.agents.researcher import PlanRejectedError, validate_call
from app.agents.schemas import ISSUE_CODES
from app.integrations.qloo_adapter import EvidenceSource, FixtureError, QlooPayload
from app.integrations.qloo_client import QlooError
from app.schemas.brief import DecisionBrief
from app.schemas.evidence import EvidenceRecord, make_error_record, stable_evidence_id
from app.services.criterion_extraction import FORMULAS, extract_raw_values
from app.services.decision_engine import score_concepts
from app.services.evidence_normalizer import normalize_response
from app.services.robustness import analyze_sensitivity
from app.services.persistence import (
    add_critic_finding,
    add_evidence_records,
    add_score_snapshot,
    add_workflow_event,
    create_run,
    get_run_bundle,
    get_run_state,
    load_evidence_records,
    set_revision_count,
    update_run_state,
)
from app.workflow.states import RunState
from app.workflow.transitions import transition

SCORING_VERSION_DEFAULT = "v0.1"
WORKFLOW_VERSION = "w0.1-g2"
MAX_LIVE_CALLS_PER_RUN = 10
# How many evidence ids per concept the analyst may cite (payload size cap).
MAX_EVIDENCE_IDS_PER_CONCEPT = 20
# Two concepts count as tied when their weighted totals are within this many
# points of each other on the 0-100 scale (human decision, 2026-10-22).
TIE_EPSILON_POINTS = 0.5


def _tiebreak_retrieval(
    source: EvidenceSource,
    brief: DecisionBrief,
    tied: list[str],
    records_by_concept: dict[str, list[EvidenceRecord]],
    calls_made: int,
    max_calls: int,
) -> tuple[dict[str, list[EvidenceRecord]], int, int, int]:
    """Look harder at the tied concepts: one refined search each.

    Returns (new_records_by_concept, extra_calls, new_entities,
    known_entities_skipped). An entity that is already known for a concept is
    NOT added again - the same entity is the same entity, and counting it
    twice would quietly inflate that concept's score.
    """
    new_records: dict[str, list[EvidenceRecord]] = {cid: [] for cid in tied}
    extra_calls = 0
    new_entities = 0
    skipped = 0
    names = {c.concept_id: c.name for c in brief.concepts}
    for cid in tied:
        if calls_made + extra_calls >= max_calls:
            break
        query = f"{names.get(cid, cid)} {brief.market}".strip()
        try:
            payload = source.load("search", {"query": query})
        except (FixtureError, QlooError):
            continue
        extra_calls += 1
        known = {
            r.qloo_entity_id
            for r in records_by_concept.get(cid, [])
            if r.qloo_entity_id
        }
        for rec in normalize_response(payload, intended_name=names.get(cid, cid)):
            if rec.qloo_entity_id and rec.qloo_entity_id in known:
                skipped += 1
                continue
            if rec.qloo_entity_id:
                known.add(rec.qloo_entity_id)
            new_records[cid].append(rec)
            new_entities += 1
    return new_records, extra_calls, new_entities, skipped


def _detect_tie(scores: list[Any], epsilon: float = TIE_EPSILON_POINTS) -> dict[str, Any]:
    """Name the concepts that are level with the leader (2026-10-22).

    A live run had all three concepts on exactly the same total and still
    declared one winner. The tie is now detected and reported, so the page
    can say "A and B are tied" instead of implying a difference.
    """
    ranked = [
        s
        for s in scores
        if getattr(s, "rank", None) is not None
        and getattr(s, "weighted_total", None) is not None
    ]
    if not ranked:
        return {"detected": False, "concepts": [], "spread": None, "threshold": epsilon}
    ranked.sort(key=lambda s: (-float(s.weighted_total), s.concept_id))
    top = float(ranked[0].weighted_total)
    tied = [
        s.concept_id
        for s in ranked
        if abs(top - float(s.weighted_total)) <= epsilon
    ]
    spread = round(top - min(float(s.weighted_total) for s in ranked if s.concept_id in tied), 4)
    return {
        "detected": len(tied) > 1,
        "concepts": tied,
        "spread": spread,
        "threshold": epsilon,
        "top_total": round(top, 4),
    }


# --------------------------------------------------------------------------
# The verbose report (2026-10-22, Batch 3): the number guard.
#
# The reporter model may only use numbers from the payload it was given (or
# that number rounded to one decimal, or a percent phrasing of a payload
# fraction). These helpers decide that deterministically: they are the reason
# an invented "47 percent of the market" can never reach the page.
# --------------------------------------------------------------------------

_NUM_TOKEN_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w])")

# Keys whose strings are identifiers (hex ids, version tags), never prose -
# their digit runs would quietly legalise invented numbers.
_NUMBER_SKIP_KEYS = frozenset(
    {
        "claim_id",
        "evidence_ids",
        "evidence_id",
        "qloo_entity_id",
        "entity_id",
        "run_id",
        "scoring_version",
        "workflow_version",
    }
)


def _collect_allowed_numbers(
    node: Any, out: set[float] | None = None, key: str | None = None
) -> set[float]:
    """Every number that is legal in the verbose prose: payload numbers plus
    numbers inside the payload's own prose fields, minus identifier digit
    runs. A 32-hex run inside a string is not a number."""
    out = set() if out is None else out
    if isinstance(node, dict):
        for k, v in node.items():
            _collect_allowed_numbers(v, out, k if isinstance(k, str) else None)
    elif isinstance(node, list):
        for v in node:
            _collect_allowed_numbers(v, out, key)
    elif isinstance(node, bool):
        pass
    elif isinstance(node, (int, float)):
        out.add(float(node))
    elif isinstance(node, str) and key not in _NUMBER_SKIP_KEYS:
        if not re.fullmatch(r"[0-9a-fA-F-]{8,}", node):
            for m in _NUM_TOKEN_RE.finditer(node):
                token = m.group(1)
                if len(token.split(".")[0]) <= 6:
                    out.add(float(token))
    return out


def _number_ok(token: str, allowed: set[float]) -> bool:
    value = float(token)
    decimals = len(token.partition(".")[2])
    for v in allowed:
        if round(v, decimals) == value:
            return True
        # A percent phrasing of a payload fraction: 0.25 -> "25 percent".
        if round(v * 100.0, decimals) == value:
            return True
    return False


def _number_violations(prose: str, allowed: set[float]) -> list[tuple[str, float]]:
    return [
        (m.group(1), float(m.group(1)))
        for m in _NUM_TOKEN_RE.finditer(prose)
        if not _number_ok(m.group(1), allowed)
    ]


class _NumberGuardError(ValueError):
    """Raised (internally) so the retry hint can NAME the offending numbers."""

    def __init__(self, tokens: list[str]) -> None:
        super().__init__("prose used numbers that are not in the payload")
        self.hint = (
            "REJECTED: your prose used the number(s) " + ", ".join(tokens)
            + " which do not appear in the payload. Rewrite the report using "
            "ONLY numbers from the payload (or their one-decimal rounding, or "
            "a percent phrasing of a payload fraction). No other numbers may "
            "appear."
        )


def _move(
    engine: Engine,
    run_id: str,
    seq: int,
    current: RunState,
    target: RunState,
    detail: dict[str, Any] | None = None,
) -> tuple[RunState, int]:
    nxt = transition(current, target)
    seq += 1
    add_workflow_event(engine, run_id, seq, nxt.value, f"enter_{nxt.value.lower()}", detail or {})
    update_run_state(engine, run_id, nxt.value)
    return nxt, seq


def _plan_calls(brief: DecisionBrief, source: EvidenceSource) -> list[tuple[str | None, str, dict[str, str]]]:
    """Deterministic retrieval plan: one search per concept (concept evidence),
    plus ONE shared insights call on the concept tag (market evidence, attached
    to every concept). Shared market evidence is semantically honest: C3 market
    relevance is market-level, and one call costs 1 quota instead of 3."""
    calls: list[tuple[str | None, str, dict[str, str]]] = []
    for concept in brief.concepts:
        calls.append((concept.concept_id, "search", {"query": concept.name}))
    tag_urn = getattr(source, "tag_urn", None)
    if tag_urn:
        calls.append(
            (
                None,
                "insights",
                {"filter.type": "urn:entity:place", "filter.tags": tag_urn},
            )
        )
    return calls


def _resolve_category_tag(
    source: EvidenceSource, category: str
) -> tuple[str | None, dict[str, Any]]:
    """Resolve a category phrase to a place-category tag URN, live.

    Uses the docs-verified /v2/tags endpoint (filter.query; 2026-10-16) and
    picks the most popular 'urn:tag:category:place:' hit. Returns
    (urn | None, detail) - None is a recorded outcome (limitation), never a
    guessed tag. Lives in the coordinator so the planner layer cannot
    accidentally hand a model-written URN to Qloo.
    """
    payload = source.load("tags", {"filter.query": category})
    results = payload.payload.get("results") if isinstance(payload.payload, dict) else None
    tags = results.get("tags") if isinstance(results, dict) else None
    detail: dict[str, Any] = {"filter_query": category, "tag_count": len(tags) if isinstance(tags, list) else 0}
    if not isinstance(tags, list) or not tags:
        return None, detail
    candidates = [
        t for t in tags
        if isinstance(t, dict) and str(t.get("id", "")).startswith("urn:tag:category:place:")
    ]
    if not candidates:
        # 2026-10-24 live verification: museum-type categories resolve only
        # inside the genre family (no category:place:museum exists).
        candidates = [
            t for t in tags
            if isinstance(t, dict) and str(t.get("id", "")).startswith("urn:tag:genre:place:")
        ]
        if candidates:
            detail["family"] = "genre:place"
    if not candidates:
        detail["reason"] = "no place-category/genre tag in the response"
        return None, detail
    winner = max(candidates, key=lambda t: float(t.get("popularity") or 0.0))
    detail.update({"resolved": winner.get("id"), "name": winner.get("name")})
    return str(winner.get("id")), detail


def _validate_agent_plan(
    plan: list[tuple[str | None, str, dict[str, str]]],
    known_concepts: list[str],
    max_calls: int,
) -> tuple[list[tuple[str | None, str, dict[str, str]]], list[str]]:
    """Code-side enforcement for researcher-proposed plans.

    Per CALL, not per plan: one malformed call is dropped and reported, the
    rest of the plan survives (live finding 2026-10-20: a param named
    "filter" made the whole plan unusable and the deterministic planner took
    over). The rules live in app.agents.researcher.validate_call so the
    agent layer and this layer cannot drift apart.
    """
    limitations: list[str] = []
    kept: list[tuple[str | None, str, dict[str, str]]] = []
    for owner, endpoint, params in plan:
        errors = validate_call(endpoint, params)
        if errors:
            limitations.append(f"rejected planned call: {errors[0]}")
            continue
        if owner is not None and owner not in known_concepts:
            limitations.append(f"rejected planned call: unknown concept {owner!r}")
            continue
        kept.append((owner, endpoint, params))
    if len(kept) > max_calls:
        limitations.append(f"plan truncated to call budget: {len(kept)} > {max_calls}")
        kept = kept[:max_calls]
    return kept, limitations


def _unwrap_hook_output(value: Any) -> tuple[list[Any], list[str], str]:
    """Hook results may be a plain list (legacy) or an AgentOutput carrier.

    Returns (items, rejection_notes, raw_head). Nothing is ever silently
    dropped: the notes travel to the run's limitations and the raw payload
    (truncated) is persisted as a workflow event.
    """
    items = getattr(value, "items", None)
    if items is None:
        return list(value), [], ""
    return (
        list(items),
        list(getattr(value, "rejected", []) or []),
        str(getattr(value, "raw_head", "") or ""),
    )


def _accepts_repair_hint(fn: Any) -> bool:
    """True when the hook can receive the code's rejection reason."""
    import inspect

    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    if "repair_hint" in sig.parameters:
        return True
    return any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values())


def _call_hook(fn: Any, args: tuple, hint: str | None) -> Any:
    """Call a hook, passing the repair hint when the hook supports it."""
    if hint and _accepts_repair_hint(fn):
        return fn(*args, repair_hint=hint)
    return fn(*args)


def _repair_hint(exc: Exception) -> str:
    """Turn a validation failure into an instruction the model can act on.

    Live finding (2026-10-20): the retry re-sent the IDENTICAL prompt at
    temperature 0, so the model produced the identical invalid output and the
    second attempt was wasted. The retry now carries the reason.
    """
    return (
        "Your previous output was rejected by code validation and was discarded. "
        f"Reason: {str(exc)[:300]}. "
        "Return the FULL corrected JSON, using only the documented field names "
        "and the allowed values listed in the instructions."
    )


def _salvage_claims(
    claims: list[dict[str, Any]], known_concepts: list[str], known_ids: set[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep the claims that satisfy the hard invariants, report the rest."""
    kept: list[dict[str, Any]] = []
    rejected: list[str] = []
    for claim in claims:
        try:
            _validate_claims([claim], known_concepts, known_ids)
        except ValueError as exc:
            rejected.append(f"claim {claim.get('claim_id')!r}: {exc}")
            continue
        kept.append(claim)
    return kept, rejected


def _salvage_findings(
    findings: list[dict[str, Any]], known_concepts: list[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep the findings that satisfy the hard invariants, report the rest."""
    kept: list[dict[str, Any]] = []
    rejected: list[str] = []
    for finding in findings:
        try:
            _validate_critic_output([finding], known_concepts)
        except ValueError as exc:
            rejected.append(f"finding {finding.get('issue_code')!r}: {exc}")
            continue
        kept.append(finding)
    return kept, rejected


_CAUSAL_PHRASES = (
    "will succeed", "will fail", "drives ", "guarantees", "proves ",
    "purchase intent", "will buy", "because of",
)


def _deterministic_critic(
    claims: list[dict[str, Any]],
    known_ids: set[str],
    available_by_concept: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Rule checks only: unknown evidence IDs, missing evidence, causal phrasing.

    MISSING_EVIDENCE is judged from the EVIDENCE the concept actually has
    (available_by_concept), not from whether the claim happens to carry an id
    list. Live finding (2026-10-22): the old rule fired on every claim
    because the analyst was told to leave evidence_ids empty, so the report
    said "no available evidence backs this concept's claim" for concepts with
    40 of 40 records available.
    """
    findings: list[dict[str, Any]] = []
    available = available_by_concept or {}
    for claim in claims:
        missing = [eid for eid in claim.get("evidence_ids", []) if eid not in known_ids]
        if missing:
            findings.append(
                {
                    "issue_code": "UNSUPPORTED_CLAIM",
                    "severity": "major",
                    "affected_concept_id": claim["concept_id"],
                    "affected_claim_id": claim["claim_id"],
                    "evidence_ids": [],
                    "explanation": "claim cites evidence IDs not present in this run",
                    "suggested_action": "remove",
                    "source": "rules",
                }
            )
        concept_id = claim.get("concept_id")
        if available.get(concept_id, 0) == 0 and not claim.get("evidence_ids"):
            findings.append(
                {
                    "issue_code": "MISSING_EVIDENCE",
                    "severity": "minor",
                    "affected_concept_id": claim["concept_id"],
                    "affected_claim_id": claim["claim_id"],
                    "evidence_ids": [],
                    "explanation": "no available evidence backs this concept's claim",
                    "suggested_action": "qualify",
                    "source": "rules",
                }
            )
        lowered = str(claim.get("text", "")).lower()
        if claim.get("claim_type") != "observation" and any(p in lowered for p in _CAUSAL_PHRASES):
            findings.append(
                {
                    "issue_code": "CAUSAL_OVERCLAIM",
                    "severity": "minor",
                    "affected_concept_id": claim["concept_id"],
                    "affected_claim_id": claim["claim_id"],
                    "evidence_ids": [],
                    "explanation": "causal phrasing without cited causal evidence",
                    "suggested_action": "revise_wording",
                }
            )
    return findings


def _validate_claims(
    claims: list[dict[str, Any]], known_concepts: list[str], known_ids: set[str]
) -> list[dict[str, Any]]:
    """Hard invariants for analyst output: known concepts, no invented evidence."""
    if not claims:
        raise ValueError("analyst returned no claims")
    for claim in claims:
        if claim.get("concept_id") not in known_concepts:
            raise ValueError(f"claim targets unknown concept {claim.get('concept_id')!r}")
        invented = [eid for eid in claim.get("evidence_ids", []) if eid not in known_ids]
        if invented:
            raise ValueError(f"claim {claim.get('claim_id')!r} cites unknown evidence IDs")
    return claims


def _validate_critic_output(
    findings: list[dict[str, Any]], known_concepts: list[str]
) -> list[dict[str, Any]]:
    """Hard invariants for critic output: closed issue codes, closed severity
    and action values, known concepts.

    The severity check is repeated here (the agent wrapper applies the
    pydantic schema as well) so a hook that returns raw dicts cannot smuggle
    a value the report does not define.
    """
    from app.agents.schemas import ISSUE_CODES

    for finding in findings:
        if finding.get("issue_code") not in ISSUE_CODES:
            raise ValueError(f"unknown issue code {finding.get('issue_code')!r}")
        if finding.get("severity") not in ("major", "minor", "info"):
            raise ValueError(
                f"unknown severity {finding.get('severity')!r} (expected major, minor or info)"
            )
        if finding.get("affected_concept_id") not in known_concepts:
            raise ValueError(f"finding targets unknown concept {finding.get('affected_concept_id')!r}")
        if finding.get("suggested_action") not in ("remove", "qualify", "revise_wording"):
            raise ValueError(f"unknown suggested action {finding.get('suggested_action')!r}")
    return findings


CONCEPT_NOTE_MAX_CHARS = 900  # shortcut: hard cap, upgrade = reject-and-retry if truncation shows up in a demo


def _template_concept_notes(
    rows: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    findings_by_concept: dict[str, int],
) -> dict[str, Any]:
    """The deterministic per-concept critique notes (never an LLM).

    Each note states only computed facts: rank, weighted total, evidence
    coverage, and the critique's recorded findings for the concept. Used
    when no concept-critic hook is configured or its output could not be
    used safely (validation, the number guard, twice).
    """
    ranked = [r for r in rows if r.get("status") == "RANKED"]
    rank_of = len(ranked) or len(rows)
    notes: dict[str, str] = {}
    for row in rows:
        cid = row["concept_id"]
        if row.get("status") != "RANKED":
            notes[cid] = (
                "Not ranked, so there is no critique of weak points against "
                f"peers: {row.get('reason') or 'the engine excluded this concept.'}"
            )
            continue
        count = findings_by_concept.get(cid, 0)
        notes[cid] = (
            f"Rank {row['rank']} of {rank_of}; weighted total "
            f"{row['weighted_total']} (computed); coverage "
            f"{row.get('coverage')} evidence records. The critique recorded "
            f"{count} finding(s) for this concept"
            + ("." if count == 0 else "; see the critique section for them.")
        )
        notes[cid] = notes[cid][:CONCEPT_NOTE_MAX_CHARS]
    winner = next((r for r in ranked if r.get("rank") == 1), None)
    if winner is not None and ranked:
        second = ranked[1] if len(ranked) > 1 else None
        margin = (
            f" The runner-up trails by "
            f"{winner['weighted_total'] - second['weighted_total']:.1f} weighted points."
            if second
            else " It was the only ranked concept."
        )
        winner_note = (
            f"Winner: {winner.get('name') or winner['concept_id']} — rank 1 of "
            f"{len(ranked)} ranked concepts, weighted total "
            f"{winner['weighted_total']} (computed).{margin} Evidence coverage: "
            f"{winner.get('coverage')} records available. This is a computed "
            f"screening result under the user's weights, not a demand forecast."
        )
        winner_note = winner_note[:CONCEPT_NOTE_MAX_CHARS]
    else:
        winner_note = "No concept ranked, so there is no winner note."
    return {"notes": notes, "winner_note": winner_note, "llm_written": False}


def _template_verbose_report(brief: DecisionBrief, report: dict[str, Any]) -> str:
    """The deterministic verbose report (never an LLM).

    Written from the computed report only, so it is honest by construction.
    Used whenever the reporter model may not or cannot write: no LLM
    configured, the critique did not complete, or the model kept writing
    numbers that are not in the payload.
    """
    names = {c.concept_id: c.name for c in brief.concepts}
    ranks = report.get("ranks", [])
    ranked = [r for r in ranks if r.get("status") == "RANKED"]
    ranked.sort(key=lambda r: (r.get("rank") or 99, r["concept_id"]))
    infeasible = [r for r in ranks if r.get("status") != "RANKED"]
    research = report.get("research", {})
    sensitivity = report.get("sensitivity", {})
    claims = report.get("claims", [])
    critique = report.get("critic", {})
    limitations = report.get("limitations", [])

    parts: list[str] = []

    parts.append(
        f"The brief asked which of three competing product concepts to take "
        f"forward for the business goal: {brief.business_goal}. The market was "
        f"{brief.market}; the intended audience: {brief.audience_description}. "
        f"The three concepts entered were "
        + ", ".join(f"{names.get(c.concept_id, c.concept_id)} ({c.concept_id})" for c in brief.concepts)
        + "."
    )
    plan_owner = research.get("mode", "deterministic")
    raw_calls = research.get("calls")
    call_count = len(raw_calls) if isinstance(raw_calls, list) else research.get("qloo_calls", 0)
    parts.append(
        f"Evidence was retrieved with {plan_owner} planning in "
        f"{call_count} Qloo call(s): "
        f"{research.get('evidence', {}).get('available', 0)} of "
        f"{research.get('evidence', {}).get('total', 0)} evidence records carry "
        f"usable data, split across the concepts as "
        + ", ".join(
            f"{names.get(cid, cid)} {counts.get('available', 0)}/{counts.get('total', 0)}"
            for cid, counts in research.get("evidence", {}).get("per_concept", {}).items()
        )
        + ". Each record keeps its source, query and coverage, listed in full in "
        "the evidence section."
    )

    if ranked:
        lead = ranked[0]
        headers = [
            r for r in ranks
            if r.get("weighted_total") is not None
            and len([x for x in ranks if x.get("weighted_total") == r.get("weighted_total")]) > 1
        ]
        if headers:
            tied_names = ", ".join(
                names.get(r["concept_id"], r["concept_id"]) for r in headers
            )
            parts.append(
                f"Two or more concepts are LEVEL on the weighted total: {tied_names}. "
                "The engine does not invent a difference it cannot measure. "
                + report.get("tiebreak", {}).get("note", "")
                + " Cultural affinity is not purchase intent: the order is a "
                "screening rank, not a demand forecast."
            )
        else:
            parts.append(
                f"{names.get(lead['concept_id'], lead['concept_id'])} leads the screening "
                f"with a weighted total of {lead['weighted_total']:.1f} of 100 and "
                f"evidence coverage of {lead['coverage'] * 100:.1f} percent. Its "
                "per-criterion values: "
                + ", ".join(
                    f"{c['criterion']} {c['value']:.2f} (weight {c['weight_applied'] * 100:.0f} percent)"
                    for c in lead.get("criterion_scores", [])
                    if c.get("value") is not None
                )
                + "."
            )
            if len(ranked) > 1:
                parts.append(
                    "The other ranked concepts: "
                    + "; ".join(
                        f"{names.get(r['concept_id'], r['concept_id'])} at "
                        f"{r['weighted_total']:.1f} (coverage "
                        f"{r['coverage'] * 100:.1f} percent)"
                        for r in ranked[1:]
                    )
                    + "."
                )
        for r in ranked:
            stmt = sensitivity.get("statements", {}).get(r["concept_id"])
            if stmt:
                sentence = str(stmt).rstrip(".")
                parts.append(f"{names.get(r['concept_id'], r['concept_id'])}: {sentence}.")
    if infeasible:
        parts.append(
            "Not ranked, and why: "
            + "; ".join(
                f"{names.get(r['concept_id'], r['concept_id'])} — "
                f"{r.get('reason') or 'it fails the hard constraints'}"
                for r in infeasible
            )
            + "."
        )
    if claims:
        parts.append(
            "The analysis notes: "
            + " ".join(
                f"({names.get(c.get('concept_id'), c.get('concept_id'))}) "
                f"{c.get('text', '')}" for c in claims
            )
        )
    if critique.get("claims_reviewed"):
        if critique.get("findings_count"):
            parts.append(
                f"The critique reviewed {critique['claims_reviewed']} claim(s) and "
                f"raised {critique['findings_count']} finding(s) "
                f"({critique.get('llm_findings', 0)} from the critic model, "
                f"{critique.get('rule_findings', 0)} from the deterministic rule "
                "checks). The affected claims are qualified in the critique "
                "section, verbatim."
            )
        else:
            parts.append(
                f"The critique reviewed {critique['claims_reviewed']} claim(s) "
                f"over {critique.get('evidence_records_available', 0)} available "
                "evidence records and found nothing to challenge. A clean "
                "critique over the full claims and evidence is a result, not an "
                "absence."
            )
    sc = sensitivity.get("scenarios_tested")
    if sc:
        tie_part = (
            f" {sensitivity.get('tie_scenarios', 0)} of the {sc} scenarios ended "
            "in a tie, and a tie is reported as a tie."
            if sensitivity.get("tie_scenarios")
            else " No scenario ended in a tie."
        )
        parts.append(
            f"The sensitivity analysis re-ran the scoring under {sc} seeded "
            "preference scenarios (the weights varied inside the ranges you "
            "set, + or - a third).\n" + tie_part
        )
    if limitations:
        parts.append(
            "Limitations recorded by the engine: " + "; ".join(limitations) + "."
        )
    parts.append(
        "Screening aid; not a demand forecast. Signals ask how well each "
        "concept fits the audience's cultural affinities, not whether it will "
        "sell."
    )
    return "\n\n".join(parts)


def preflight_constraint_check(brief: DecisionBrief) -> None:
    """Name every constraint that could never be checked, BEFORE any spend.

    The 2026-10-23 decision: a constraint only derives meaning from the
    attributes the user typed per concept. If a constraint names an attribute
    no concept declares, starting the run would burn Qloo + LLM budget and
    then surprise the human at result time. This raises with a per-concept
    list (the route maps ValueError to a 422 with this message).
    """
    problems: list[str] = []
    for constraint in brief.constraints:
        missing = sorted(
            c.concept_id
            for c in brief.concepts
            if constraint.attribute not in (c.attributes or {})
        )
        if missing:
            problems.append(
                f"hard constraint '{constraint.attribute}' = '{constraint.value}' "
                f"could never be checked: {', '.join(missing)} do not declare "
                f"the attribute '{constraint.attribute}'"
            )
    if problems:
        raise ValueError(
            "The brief cannot start as typed: "
            + "; ".join(problems)
            + ". Declare the attribute on every concept (or remove the "
            "constraint)."
        )


def run_decision(
    engine: Engine,
    brief: DecisionBrief,
    source: EvidenceSource,
    scoring_version: str = SCORING_VERSION_DEFAULT,
    workflow_version: str = WORKFLOW_VERSION,
    max_live_calls: int = MAX_LIVE_CALLS_PER_RUN,
    researcher_fn=None,
    analyst_fn=None,
    critic_fn=None,
    revise_fn=None,
    tiebreak_fn=None,
    reporter_fn=None,
    concept_critic_fn=None,
    run_id: str | None = None,
    restore_evidence: bool = False,
) -> dict[str, Any]:
    """Injectable agent hooks (G3): each defaults to the deterministic path.

    researcher_fn(names, tag_urn) -> plan list; analyst_fn(scores, evidence,
    limitations, weights) -> claim dicts; critic_fn(claims, scores, known_ids)
    -> finding dicts; revise_fn(claims, findings) -> revised claim dicts.
    A hook may also return an AgentOutput carrier (items + rejection notes +
    a truncated raw payload); a plain list still works.

    Resilience (2026-10-20): each hook is tried at most twice, and the
    second attempt is INFORMED — the validation error is handed back so the
    model can correct itself instead of repeating the same invalid output.
    Invalid individual items are dropped and reported as limitations; the
    deterministic fallback takes over only when an entire stage produced
    nothing usable.

    Resume (2026-10-22): pass an existing `run_id` to continue a half-finished
    run in place, and `restore_evidence=True` to reuse the Qloo evidence it
    already stored (no Qloo call is repeated, so a retry costs no Qloo quota).
    """
    limitations: list[str] = []
    live_calls = 0
    calls_made = 0
    restored_records: dict[str, list[EvidenceRecord]] | None = None

    if run_id is None:
        # Pre-flight (2026-10-23): a constraint naming an attribute no concept
        # declares must stop the run at the door - no run row, no Qloo call,
        # no LLM call, no surprise four minutes later.
        preflight_constraint_check(brief)
        run_id = create_run(
            engine,
            input_json=brief.model_dump(),
            scoring_version=scoring_version,
            workflow_version=workflow_version,
        )
        seq = 0
        state = RunState.CREATED
    else:
        state_value, last_seq = get_run_state(engine, run_id)
        state = RunState(state_value)
        seq = last_seq
        if restore_evidence:
            restored_records = {
                cid: [EvidenceRecord(**rec) for rec in recs]
                for cid, recs in load_evidence_records(engine, run_id).items()
            }

    def move(target: RunState, detail: dict[str, Any] | None = None) -> None:
        nonlocal state, seq
        _close_stage()
        state, seq = _move(engine, run_id, seq, state, target, detail)
        _open_stage()

    def note(event_type: str, payload: dict[str, Any]) -> None:
        """Record a non-state event (e.g. a rejected agent output) for audit."""
        nonlocal seq
        seq += 1
        add_workflow_event(engine, run_id, seq, state.value, event_type, payload)

    # How long each stage took (2026-10-22): the results page shows it, so
    # "the critic found nothing" can be read next to "the critic ran for
    # 5 minutes".
    stage_started: dict[str, float] = {}
    stage_seconds: list[dict[str, Any]] = []

    def _open_stage() -> None:
        stage_started[state.value] = time.monotonic()

    def _close_stage() -> None:
        started = stage_started.pop(state.value, None)
        if started is not None:
            stage_seconds.append(
                {"stage": state.value, "seconds": round(time.monotonic() - started, 1)}
            )

    if state is RunState.CREATED:
        move(RunState.VALIDATING_INPUT)
    elif state is not RunState.FAILED_RETRYABLE:
        # A resume is a retryable failure in the state table's own words.
        # FAILED_RETRYABLE may only continue into RETRIEVING_EVIDENCE, which
        # is exactly where a resumed run re-enters the pipeline.
        move(
            RunState.FAILED_RETRYABLE,
            {"resumed": True, "restored_evidence": bool(restored_records)},
        )
    move(RunState.RETRIEVING_EVIDENCE)

    records_by_concept: dict[str, list[EvidenceRecord]] = {c.concept_id: [] for c in brief.concepts}
    fixture_flags: list[bool] = []
    concept_names = {c.concept_id: c.name for c in brief.concepts}
    concept_ids = [c.concept_id for c in brief.concepts]
    calls: list[tuple[str | None, str, dict[str, str]]] = []
    research_mode = "deterministic"
    agent_category: str | None = None
    if restored_records is not None:
        # RESUME: the previous attempt already paid for the Qloo calls.
        records_by_concept = {
            cid: list(recs) for cid, recs in restored_records.items()
        }
        for cid in records_by_concept:
            records_by_concept.setdefault(cid, [])
        limitations.append(
            f"resumed run: reused {sum(len(r) for r in records_by_concept.values())} "
            "stored evidence records (no Qloo call repeated)"
        )
    elif researcher_fn is not None:
        # The researcher gets the same two chances as the other agents, and
        # the second one is INFORMED: the rejection reason is handed back so
        # the model can fix the plan instead of repeating it.
        plan_hint: str | None = None
        last_plan_error: Exception | None = None
        for _attempt in range(2):
            try:
                proposed = _call_hook(
                    researcher_fn,
                    ([c.name for c in brief.concepts], brief.category),
                    plan_hint,
                )
            except Exception as exc:
                last_plan_error = exc
                plan_hint = _repair_hint(exc)
                continue
            proposed_calls, agent_rejected, raw_head = _unwrap_hook_output(proposed)
            # The researcher names the category on the hook carrier too (it
            # does not go through salvage; it is a phrase, not evidence).
            agent_category = getattr(proposed, "category", None) or None
            calls, plan_limits = _validate_agent_plan(
                proposed_calls, concept_ids, max_live_calls
            )
            if calls:
                limitations.extend(plan_limits)
                research_mode = "agent"
                for note_text in agent_rejected:
                    limitations.append(f"researcher plan: {note_text[:160]}")
                if agent_rejected:
                    note(
                        "agent_output_rejected",
                        {
                            "stage": "researcher",
                            "rejected": agent_rejected,
                            "raw_head": raw_head[:600],
                        },
                    )
                break
            plan_hint = (
                "Your previous plan was rejected: "
                + "; ".join((plan_limits + agent_rejected)[:5])[:300]
            )
            last_plan_error = PlanRejectedError(plan_hint)
        if not calls:
            calls = _plan_calls(brief, source)
            limitations.append(
                f"researcher plan failed ({type(last_plan_error).__name__}: "
                f"{str(last_plan_error)[:180]}); deterministic plan used"
            )
    else:
        calls = _plan_calls(brief, source)

    # The market-level insights call is CODE-planned (2026-10-24): the
    # category is named by the researcher (or the brief), and the tag URN is
    # resolved live from the docs-verified /v2/tags endpoint - never
    # model-written (a URN not received from Qloo is an invented identifier).
    # Fixture mode is untouched: the synthetic loader has no tags fixture, so
    # fixture runs keep their exact search-only behavior.
    if getattr(source, "is_live", False) and restored_records is None:
        category = (agent_category or brief.category or "").strip()
        if not category:
            limitations.append(
                "no category named (by the researcher or the brief); the "
                "market-level insights call was skipped - C3 market evidence "
                "is absent this run"
            )
        elif len(calls) + 2 > max_live_calls:
            limitations.append(
                "call budget too small for tag resolution plus the insights "
                "call; the market-level insights call was skipped"
            )
        else:
            try:
                tag_urn, resolve_detail = _resolve_category_tag(source, category)
            except (QlooError, FixtureError, ValueError) as exc:
                tag_urn, resolve_detail = None, {"error": str(exc)[:200]}
            if tag_urn:
                note("category_tag_resolved", resolve_detail)
                calls.append(
                    (
                        None,
                        "insights",
                        {
                            "filter.type": "urn:entity:place",
                            "filter.tags": tag_urn,
                            # 2026-10-24 live-verified (P1a): the market text
                            # rides the SAME call as a signal - affinity is
                            # re-ranked for the market, zero extra quota. The
                            # verbatim user string keeps provenance honest.
                            "signal.location.query": brief.market,
                        },
                    )
                )
            else:
                resolve_detail["category"] = category
                note("category_tag_unresolved", resolve_detail)
                limitations.append(
                    f"category {category!r} resolved to no place-category tag "
                    "(live): the market-level insights call was skipped - "
                    "C3 market evidence is absent this run"
                )
    for owner_id, endpoint, params in calls:
        calls_made += 1
        if getattr(source, "is_live", False):
            live_calls += 1
            if live_calls > max_live_calls:
                limitations.append(f"call budget exceeded: stopped after {max_live_calls} live Qloo calls")
                break
        try:
            payload: QlooPayload = source.load(endpoint, params)
        except FixtureError as exc:
            limitations.append(f"{endpoint} unavailable in fixture mode: {exc}")
            continue
        except QlooError as exc:
            targets = [owner_id] if owner_id is not None else list(records_by_concept)
            for target in targets:
                records_by_concept[target].append(
                    make_error_record(
                        endpoint_or_operation=endpoint,
                        query_params_redacted=params,
                        error_code=exc.code,  # type: ignore[arg-type]
                        source="qloo" if getattr(source, "is_live", False) else "fixture",
                        fixture_mode=not getattr(source, "is_live", False),
                        limitations=[exc.message_safe or "Qloo call failed"],
                    )
                )
            if endpoint == "insights":
                # A failed SHARED market call removes C3 evidence for every
                # concept at once - louder than a per-record limitation.
                limitations.append(
                    f"the shared market insights call failed "
                    f"({exc.code}: {(exc.message_safe or '')[:120]}); "
                    "C3 market evidence is absent this run"
                )
            continue
        targets = [owner_id] if owner_id is not None else list(records_by_concept)
        for target in targets:
            recs = normalize_response(payload, intended_name=concept_names[target])
            records_by_concept[target].extend(recs)
        fixture_flags.append(payload.fixture_mode)

    for concept_id, recs in records_by_concept.items():
        for rec in recs:
            # Run- AND concept-scope the deterministic ID up front: shared
            # market evidence attached to several concepts (and any repeat run)
            # must not collide on the evidence_records primary key, and claims
            # must cite the persisted IDs. Scores are unaffected (IDs are
            # provenance, not score inputs).
            rec.evidence_id = stable_evidence_id(
                f"{rec.endpoint_or_operation}#{run_id}#{concept_id}",
                rec.query_params_redacted,
                rec.qloo_entity_id,
            )

    # Incremental persistence (2026-10-22): the evidence is stored as soon as
    # it exists, so a failure later in the pipeline (or a dead process) leaves
    # a resumable run instead of nothing.
    for concept_id, recs in records_by_concept.items():
        if recs:
            add_evidence_records(
                engine,
                run_id,
                [
                    {**r.model_dump(exclude={"retrieved_at"}), "concept_id": concept_id}
                    for r in recs
                ],
            )

    # What the researcher did and found (2026-10-22): the retrieval plan and
    # the evidence it produced, so the page can show the work instead of
    # asking the reader to trust it.
    research_block = {
        "mode": (
            "resumed"
            if restored_records is not None
            else ("agent" if research_mode == "agent" else "deterministic")
        ),
        "calls": [
            {"endpoint": endpoint, "params": params, "owner": owner}
            for owner, endpoint, params in calls
        ],
        "evidence": {
            "total": sum(len(recs) for recs in records_by_concept.values()),
            "available": sum(
                1
                for recs in records_by_concept.values()
                for r in recs
                if r.coverage_status == "available"
            ),
            "per_concept": {
                cid: {
                    "available": sum(
                        1 for r in recs if r.coverage_status == "available"
                    ),
                    "total": len(recs),
                }
                for cid, recs in records_by_concept.items()
            },
        },
        "qloo_calls": live_calls,
    }

    move(RunState.NORMALIZING_EVIDENCE)
    raw_values, diagnostics = extract_raw_values(records_by_concept)
    if all(v is None for per_concept in raw_values.values() for v in per_concept.values()):
        terminal = RunState.FAILED_TERMINAL
        move(terminal)
        update_run_state(
            engine, run_id, terminal.value,
            error_code="QLOO_NO_MATCH", error_message_safe="no usable evidence for any concept",
            final_report_json={"run_id": run_id, "state": terminal.value,
                               "limitations": sorted(set(limitations + ["no usable evidence for any concept"]))},
        )
        return {"run_id": run_id, "state": terminal.value, "report": None, "persisted": terminal.value}
    move(RunState.SCORING)

    scores = score_concepts(
        concept_ids=concept_ids,
        weights=brief.weights,
        raw_values=raw_values,
        hard_constraints=brief.constraints,
        scoring_version=scoring_version,
        concept_attributes={c.concept_id: dict(c.attributes) for c in brief.concepts},
    )

    for recs in records_by_concept.values():
        for rec in recs:
            if rec.coverage_status != "available":
                limitations.append(
                    f"{rec.qloo_entity_id or 'unresolved'}: coverage {rec.coverage_status}"
                )
    for recs in records_by_concept.values():
        for rec in recs:
            limitations.extend(f"evidence: {lim}" for lim in rec.limitations if "ENTITY_MATCH_AMBIGUOUS" in lim)

    # TIE-BREAK (2026-10-22, Batch 2): when the deterministic scoring leaves
    # the leaders level, look harder - more Qloo for the tied concepts, the
    # totals recomputed, and a focused LLM comparison of the two.
    known_ids = {r.evidence_id for recs in records_by_concept.values() for r in recs}
    tie = _detect_tie(scores)
    tiebreak_block: dict[str, Any] = {
        "detected": False,
        "concepts": [],
        "extra_calls": 0,
        "new_entities": 0,
        "known_entities_skipped": 0,
        "before": {},
        "after": {},
        "resolved": False,
        "comparison": [],
        "note": "",
    }
    tiebreak_claims: list[dict[str, Any]] = []
    if tie["detected"]:
        tied = [cid for cid in tie["concepts"] if cid in concept_ids]
        before = {
            cid: round(float(s.weighted_total), 4)
            for cid, s in ((s.concept_id, s) for s in scores)
            if cid in tied and s.weighted_total is not None
        }
        new_records, extra_calls, new_entities, skipped = _tiebreak_retrieval(
            source, brief, tied, records_by_concept, calls_made, max_live_calls
        )
        calls_made += extra_calls
        live_calls += extra_calls
        for cid, recs in new_records.items():
            for rec in recs:
                rec.evidence_id = stable_evidence_id(
                    f"{rec.endpoint_or_operation}#tiebreak#{run_id}#{cid}",
                    rec.query_params_redacted,
                    rec.qloo_entity_id,
                )
                records_by_concept.setdefault(cid, []).append(rec)
            if recs:
                add_evidence_records(
                    engine,
                    run_id,
                    [
                        {**r.model_dump(exclude={"retrieved_at"}), "concept_id": cid}
                        for r in recs
                    ],
                )
        # The tie-break's new evidence is real, stored evidence: the analyst,
        # critic, and tie-break salvage must accept its ids. Without this the
        # allow-list (built before the tie-break existed) rejects every claim
        # citing the new records - the comparison could never cite its input.
        known_ids |= {r.evidence_id for recs in records_by_concept.values() for r in recs}
        # Recompute the scores with the extra evidence.
        raw_values, diagnostics = extract_raw_values(records_by_concept)
        scores = score_concepts(
            concept_ids=concept_ids,
            weights=brief.weights,
            raw_values=raw_values,
            hard_constraints=brief.constraints,
            scoring_version=scoring_version,
            concept_attributes={c.concept_id: dict(c.attributes) for c in brief.concepts},
        )
        after = {
            cid: round(float(s.weighted_total), 4)
            for cid, s in ((s.concept_id, s) for s in scores)
            if cid in tied and s.weighted_total is not None
        }
        tie = _detect_tie(scores)
        resolved = not tie["detected"]
        note = (
            f"{len(tied)} concepts were level on the total. The tie-break made "
            f"{extra_calls} extra Qloo call(s) and added {new_entities} new "
            f"evidence record(s) ({skipped} already known, not counted twice). "
            f"After that, the totals are "
            + ", ".join(f"{cid} {after.get(cid)}" for cid in tied)
            + " — "
            + (
                "the evidence separates them."
                if resolved
                else "the evidence still cannot separate them."
            )
            + " Note: the tied concepts carry more evidence than the others, "
            "so their totals are not based on identical data."
        )
        tiebreak_block = {
            "detected": True,
            "concepts": tied,
            "extra_calls": extra_calls,
            "new_entities": new_entities,
            "known_entities_skipped": skipped,
            "before": before,
            "after": after,
            "resolved": resolved,
            "comparison": [],
            "note": note,
        }
        if not resolved and tiebreak_fn is not None:
            tied_payload = [
                {
                    "concept_id": cid,
                    "name": next(
                        (c.name for c in brief.concepts if c.concept_id == cid), cid
                    ),
                    "weighted_total": after.get(cid),
                    "criterion_scores": [
                        {"criterion": cs.criterion, "value": cs.value}
                        for cs in next(
                            (s for s in scores if s.concept_id == cid),
                            None,
                        ).criterion_scores
                    ]
                    if any(s.concept_id == cid for s in scores)
                    else [],
                }
                for cid in tied
            ]
            try:
                out = _call_hook(
                    tiebreak_fn,
                    (
                        tied_payload,
                        {
                            cid: {
                                "available": sum(
                                    1
                                    for r in records_by_concept.get(cid, [])
                                    if r.coverage_status == "available"
                                ),
                                "total": len(records_by_concept.get(cid, [])),
                                "evidence_ids": [
                                    r.evidence_id
                                    for r in records_by_concept.get(cid, [])
                                    if r.coverage_status == "available"
                                ][:MAX_EVIDENCE_IDS_PER_CONCEPT],
                            }
                            for cid in tied
                        },
                        brief.weights.as_dict(),
                        before,
                        after,
                    ),
                    None,
                )
                items, rejected, _raw = _unwrap_hook_output(out)
                good, bad = _salvage_claims(
                    [dict(c) for c in items], concept_ids, known_ids
                )
                tiebreak_claims = good
                tiebreak_block["comparison"] = good
                if bad or rejected:
                    limitations.append(
                        f"tie-break comparison: {len(bad) + len(rejected)} "
                        "claim(s) rejected by validation"
                    )
            except Exception as exc:
                limitations.append(
                    "tie-break comparison failed "
                    f"({type(exc).__name__}: {str(exc)[:180]})"
                )
                tiebreak_block["note"] += (
                    " The focused comparison could not be produced."
                )

    # The score snapshot is stored now (after the tie-break), so a later
    # failure leaves the ranks readable even without the final report.
    for s in scores:
        add_score_snapshot(
            engine,
            run_id,
            s.concept_id,
            {"status": s.status, "rank": s.rank, "weighted_total": s.weighted_total, "coverage": s.coverage},
            scoring_version,
        )

    move(RunState.DRAFTING_EXPLANATION)
    by_id = {s.concept_id: s for s in scores}
    available_by_concept = {
        cid: sum(1 for r in recs if r.coverage_status == "available")
        for cid, recs in records_by_concept.items()
    }

    def _template_claims() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for concept in brief.concepts:
            s = by_id[concept.concept_id]
            usable_ids = [
                r.evidence_id
                for r in records_by_concept[concept.concept_id]
                if r.coverage_status == "available"
            ]
            rank_text = f"rank {s.rank}" if s.rank is not None else f"status {s.status}"
            out.append(
                {
                    "claim_id": f"claim-{concept.concept_id}",
                    "concept_id": concept.concept_id,
                    "claim_type": "observation",
                    "strength": "moderate" if usable_ids else "weak",
                    "confidence": "medium" if usable_ids else "low",
                    "text": (
                        f"{concept.name} ({rank_text}, "
                        f"total {s.weighted_total if s.weighted_total is not None else 'n/a'}): "
                        f"{len(usable_ids)} of {len(records_by_concept[concept.concept_id])} evidence records available."
                    ),
                    "evidence_ids": usable_ids,
                    "score_fields": [f"{concept.concept_id}.weighted_total", f"{concept.concept_id}.rank"],
                    "audience_context": None,
                }
            )
        return out

    analyst_llm = analyst_fn is not None
    score_summary = {
        s.concept_id: {"rank": s.rank, "status": s.status, "weighted_total": s.weighted_total}
        for s in scores
    }
    evidence_summary = {
        cid: {
            "available": sum(1 for r in recs if r.coverage_status == "available"),
            "total": len(recs),
            # The REAL evidence ids for this concept, capped so the payload
            # stays small. Live finding (2026-10-22): the analyst was told to
            # leave evidence_ids empty (the payload had counts only) and both
            # critics then flagged every claim for citing nothing — the system
            # required the analyst to produce exactly what the critic had to
            # flag. A claim that cites an id that exists is checkable; an
            # invented id is still rejected by _validate_claims.
            "evidence_ids": [
                r.evidence_id
                for r in recs
                if r.coverage_status == "available"
            ][:MAX_EVIDENCE_IDS_PER_CONCEPT],
        }
        for cid, recs in records_by_concept.items()
    }
    if analyst_fn is not None:
        claims = None
        last_error: Exception | None = None
        analyst_hint: str | None = None
        rejected_notes: list[str] = []
        for _attempt in range(2):
            try:
                out = _call_hook(
                    analyst_fn,
                    (score_summary, evidence_summary, limitations, brief.weights.as_dict()),
                    analyst_hint,
                )
                candidate, agent_rejected, raw_head = _unwrap_hook_output(out)
                good, bad = _salvage_claims(
                    [dict(c) for c in candidate], concept_ids, known_ids
                )
                rejected_notes = list(agent_rejected) + list(bad)
                if not good:
                    raise ValueError("analyst output had no valid claims")
                claims = good
                if rejected_notes:
                    limitations.append(
                        f"analyst output: {len(rejected_notes)} claim(s) rejected by "
                        f"validation, {len(good)} kept"
                    )
                    for note_text in rejected_notes:
                        limitations.append(f"analyst claim rejected: {note_text[:160]}")
                    note(
                        "agent_output_rejected",
                        {
                            "stage": "analyst",
                            "rejected": rejected_notes,
                            "raw_head": raw_head[:600],
                        },
                    )
                break
            except Exception as exc:
                claims = None
                last_error = exc
                analyst_hint = _repair_hint(exc)
        if claims is None:
            analyst_llm = False
            message = (
                "analyst LLM output invalid twice "
                f"({type(last_error).__name__}: {str(last_error)[:180]}"
                "); template explanation used"
            )
            if rejected_notes:
                # Name WHY each claim was dropped (e.g. an invented evidence
                # id) instead of only the fact that it was.
                message += "; rejected: " + "; ".join(rejected_notes[:3])[:200]
            limitations.append(message)
            claims = _template_claims()
    else:
        claims = _template_claims()

    move(RunState.CRITIC_REVIEW)
    critic_llm = critic_fn is not None
    if critic_fn is not None:
        findings = None
        last_error = None
        critic_hint: str | None = None
        for _attempt in range(2):
            try:
                out = _call_hook(
                    critic_fn,
                    # The tie-break claims are reviewed as well: the critique
                    # must cover everything the run says.
                    (claims + tiebreak_claims, score_summary, sorted(known_ids)),
                    critic_hint,
                )
                candidate, agent_rejected, raw_head = _unwrap_hook_output(out)
                good, bad = _salvage_findings(
                    [dict(f) for f in candidate], concept_ids
                )
                rejected_notes = list(agent_rejected) + list(bad)
                if not good and rejected_notes:
                    # Everything the critic produced was unusable: the
                    # deterministic checks are the safety net, so the stage
                    # fails and the retry/fallback path takes over.
                    raise ValueError(
                        f"critic output had no valid findings "
                        f"({len(rejected_notes)} rejected)"
                    )
                findings = good
                # Who said it: the LLM critic or the rule checks. The UI shows
                # the source so a reader knows which critique is which.
                for finding in findings:
                    finding["source"] = "llm"
                if rejected_notes:
                    limitations.append(
                        f"critic output: {len(rejected_notes)} finding(s) rejected by "
                        f"validation, {len(good)} kept"
                    )
                    for note_text in rejected_notes:
                        limitations.append(f"critic finding rejected: {note_text[:160]}")
                    note(
                        "agent_output_rejected",
                        {
                            "stage": "critic",
                            "rejected": rejected_notes,
                            "raw_head": raw_head[:600],
                        },
                    )
                break
            except Exception as exc:
                findings = None
                last_error = exc
                critic_hint = _repair_hint(exc)
        if findings is None:
            critic_llm = False
            limitations.append(
                "critic LLM output invalid twice "
                f"({type(last_error).__name__}: {str(last_error)[:180]}"
                "); deterministic checks used"
            )
            findings = _deterministic_critic(claims, known_ids, available_by_concept)
    else:
        findings = _deterministic_critic(claims, known_ids, available_by_concept)

    revision_count = 0
    revisable = [f for f in findings if f.get("suggested_action") == "revise_wording"]
    if revisable and revise_fn is not None:
        move(RunState.REVISING)
        revised = None
        last_error = None
        revise_hint: str | None = None
        for _attempt in range(2):
            try:
                out = _call_hook(revise_fn, (claims, findings), revise_hint)
                candidate, agent_rejected, raw_head = _unwrap_hook_output(out)
                good, bad = _salvage_claims(
                    [dict(c) for c in candidate], concept_ids, known_ids
                )
                rejected_notes = list(agent_rejected) + list(bad)
                if not good:
                    raise ValueError("revision had no valid claims")
                revised = good
                if rejected_notes:
                    limitations.append(
                        f"revision output: {len(rejected_notes)} claim(s) rejected by "
                        f"validation, {len(good)} kept"
                    )
                    for note_text in rejected_notes:
                        limitations.append(f"revised claim rejected: {note_text[:160]}")
                    note(
                        "agent_output_rejected",
                        {
                            "stage": "revision",
                            "rejected": rejected_notes,
                            "raw_head": raw_head[:600],
                        },
                    )
                break
            except Exception as exc:
                revised = None
                last_error = exc
                revise_hint = _repair_hint(exc)
        if revised is not None:
            claims = revised
            revision_count = 1
            findings = findings + _deterministic_critic(claims, known_ids, available_by_concept)
        else:
            limitations.append(
                "revision failed twice "
                f"({type(last_error).__name__}: {str(last_error)[:180]}"
                "); original claims kept and qualified"
            )
            for claim in claims:
                claim["qualified"] = True
    elif revisable:
        for claim in claims:
            claim["qualified"] = True

    move(RunState.FINAL_VALIDATION)
    winner = next((s for s in scores if s.rank == 1), None)
    fixture_mode = bool(fixture_flags) and all(fixture_flags)

    # Unverifiable constraints (2026-10-23): they never blocked the concept,
    # and the run says so out loud, once per affected concept.
    for s in scores:
        if s.constraint_notice:
            limitations.append(f"{s.concept_id}: {s.constraint_notice}")

    # The per-concept critique notes (2026-10-24): drawbacks per concept plus
    # a 5-6 line winning-concept note. Same discipline as the verbose report:
    # the LLM output is id-checked, length-capped and number-guarded (twice
    # max), the deterministic notes are the fallback. One extra LLM call.
    names_map = {c.concept_id: c.name for c in brief.concepts}
    note_rows = [
        {
            "concept_id": s.concept_id,
            "name": names_map.get(s.concept_id, s.concept_id),
            "rank": s.rank,
            "status": s.status,
            "weighted_total": s.weighted_total,
            "coverage": s.coverage,
            "reason": s.infeasible_reason or s.insufficient_reason,
        }
        for s in scores
    ]
    findings_by_concept = {cid: 0 for cid in concept_ids}
    for f in findings:
        cid = f.get("affected_concept_id")
        if cid in findings_by_concept:
            findings_by_concept[cid] += 1
    template_concept_notes_block = _template_concept_notes(
        note_rows, findings, findings_by_concept
    )
    concept_notes_block = template_concept_notes_block
    if concept_critic_fn is not None and critic_llm:
        concept_note_payload = {
            "brief": {
                "market": brief.market,
                "audience_description": brief.audience_description,
            },
            "concepts": note_rows,
            "claims": [
                {k: v for k, v in c.items() if k != "evidence_ids"}
                for c in claims
            ],
            "critic_findings": findings,
            "limitations": sorted(set(limitations)),
        }
        allowed = _collect_allowed_numbers(concept_note_payload)
        allowed.add(100.0)
        cn_hint: str | None = None
        cn_result: tuple[dict[str, str], str] | None = None
        for attempt in (1, 2):
            try:
                raw = _call_hook(concept_critic_fn, (concept_note_payload,), cn_hint)
                raw_notes = raw.get("notes") if isinstance(raw, dict) else raw
                if not isinstance(raw_notes, dict) or not raw_notes:
                    raise ValueError("concept critic output carried no notes")
                raw_winner = raw.get("winner_note") if isinstance(raw, dict) else None
                if not isinstance(raw_winner, str) or not raw_winner.strip():
                    raise ValueError("concept critic output carried no winner note")
                cleaned: dict[str, str] = {}
                for cid, text in raw_notes.items():
                    safe = strip_prose_fence(str(text)) if isinstance(text, str) else ""
                    if cid not in findings_by_concept:
                        raise ValueError(f"concept note for unknown id {cid!r}")
                    if not safe:
                        raise ValueError(f"concept note for {cid} was empty")
                    cleaned[cid] = safe[:CONCEPT_NOTE_MAX_CHARS]
                if set(cleaned) != set(findings_by_concept):
                    raise ValueError("concept notes must cover every concept id")
                winner_note = strip_prose_fence(raw_winner)[:CONCEPT_NOTE_MAX_CHARS]
                joined = " ".join(cleaned.values()) + " " + winner_note
                bad = _number_violations(joined, allowed)
                if bad:
                    raise _NumberGuardError([t for t, _ in bad])
                cn_result = (cleaned, winner_note)
                break
            except _NumberGuardError as exc:
                cn_hint = exc.hint
                note(
                    "concept_notes_guard",
                    {"attempt": attempt, "guard_hint": (cn_hint or "")[:400]},
                )
            except Exception as exc:
                cn_hint = _repair_hint(exc)
        if cn_result is not None:
            concept_notes_block = {
                "notes": cn_result[0],
                "winner_note": cn_result[1],
                "llm_written": True,
                "template_used": False,
            }
        else:
            limitations.append(
                "concept notes: the model's critique notes failed validation "
                "or the number guard twice; the deterministic notes were used"
            )
            template_concept_notes_block["template_used"] = True
            template_concept_notes_block["template_reason"] = (
                "the concept model's notes could not be used safely"
            )
    else:
        template_concept_notes_block["template_used"] = True
        template_concept_notes_block["template_reason"] = (
            "no LLM concept critic is configured"
            if concept_critic_fn is None
            else "the critique did not complete; the concept critic only "
            "writes after a completed critique"
        )

    report: dict[str, Any] = {
        "run_id": run_id,
        "state": None,  # filled after terminal move
        "scoring_version": scoring_version,
        "workflow_version": workflow_version,
        "fixture_mode": fixture_mode,
        "fixture_banner": "Demo mode: fixture data, not live Qloo output." if fixture_mode else None,
        "winner": winner.concept_id if winner else None,
        "ranks": [
            {
                "concept_id": s.concept_id,
                "rank": s.rank,
                "status": s.status,
                "weighted_total": s.weighted_total,
                "coverage": s.coverage,
                # Why a concept is not ranked (hard-constraint gate or
                # coverage gate). The UI shows this verbatim, so a result with
                # no winner is never a mystery (2026-10-22).
                "reason": s.infeasible_reason or s.insufficient_reason,
                # A constraint that could not be checked never blocked this
                # concept (2026-10-23): it ranks and carries the notice.
                "constraint_notice": s.constraint_notice,
                "criterion_scores": [
                    {"criterion": c.criterion, "value": c.value, "weight_applied": c.weight_applied}
                    for c in s.criterion_scores
                ],
                "diagnostics": diagnostics[s.concept_id],
            }
            for s in scores
        ],
        "formulas": dict(FORMULAS),
        "claims": claims,
        "critic_findings": findings,
        "limitations": sorted(set(limitations)),
        "explanation_template": not analyst_llm,
        "llm_written": analyst_llm or critic_llm,
        "analyst": {"llm_written": analyst_llm, "revision_count": revision_count},
        "critic": {
            "llm_written": critic_llm,
            "findings_count": len(findings),
            "llm_findings": sum(1 for f in findings if f.get("source") == "llm"),
            "rule_findings": sum(1 for f in findings if f.get("source") == "rules"),
            # The scope of the critique (2026-10-22): "0 findings" must read as
            # "it ran and found nothing", not as "it never ran".
            # The count matches what was actually reviewed: the LLM critic
            # also receives the tie-break claims (its call above), while the
            # deterministic fallback sees only the base claims.
            "claims_reviewed": len(claims)
            + (len(tiebreak_claims) if critic_llm else 0),
            # The critique, per concept (2026-10-24): drawbacks per concept
            # plus the winning-concept note. llm_written refers to the notes
            # block only - the findings above keep their own accounting.
            "concept_notes": concept_notes_block,
            "evidence_records_available": sum(available_by_concept.values()),
            "issue_codes": list(ISSUE_CODES),
        },
        "research": research_block,
        "tie": tie,
        "tiebreak": tiebreak_block,
        "sensitivity": {"status": "pending"},
        "disclaimer": "Early screening aid. Not a demand forecast.",
    }

    move(RunState.ROBUSTNESS_ANALYSIS)
    sensitivity = analyze_sensitivity(
        concept_ids,
        raw_values,
        brief.constraints,
        {c.concept_id: dict(c.attributes) for c in brief.concepts},
        brief.weights,
        scoring_version,
    )
    report["sensitivity"] = sensitivity

    # The verbose report (2026-10-22, Batch 3). The reporter model writes the
    # full prose ONLY after the critique completed; its numbers are guarded
    # deterministically (worst case two attempts: the retry names the
    # offending number), and the deterministic template is the fallback.
    move(RunState.REPORTING)
    names = {c.concept_id: c.name for c in brief.concepts}
    verbose_note = ""
    attempts = 0
    verbose_prose: str | None = None
    if reporter_fn is not None and critic_llm:
        reporter_payload = {
            "brief": {
                "market": brief.market,
                "audience_description": brief.audience_description,
                "business_goal": brief.business_goal,
            },
            "concepts": [
                {
                    "concept_id": r["concept_id"],
                    "name": names.get(r["concept_id"], r["concept_id"]),
                    "rank": r["rank"],
                    "status": r["status"],
                    "weighted_total": r["weighted_total"],
                    "coverage": r["coverage"],
                    "reason": r.get("reason"),
                    "criterion_scores": r.get("criterion_scores", []),
                }
                for r in report["ranks"]
            ],
            "claims": [
                {k: v for k, v in c.items() if k != "evidence_ids"}
                for c in claims
            ],
            "critic_findings": findings,
            "tie": tie,
            "tiebreak": tiebreak_block,
            "sensitivity": sensitivity,
            "research": {
                "mode": research_block.get("mode"),
                "calls": research_block.get("calls"),
                "evidence": research_block.get("evidence"),
                "qloo_calls": research_block.get("qloo_calls"),
            },
            "limitations": report["limitations"],
        }
        allowed = _collect_allowed_numbers(reporter_payload)
        allowed.add(100.0)
        hint: str | None = None
        for attempt in (1, 2):
            attempts = attempt
            try:
                raw = _call_hook(reporter_fn, (reporter_payload,), hint)
                prose = (
                    raw.get("report")
                    if isinstance(raw, dict)
                    else str(raw)
                )
                prose = strip_prose_fence(str(prose))
                bad = _number_violations(prose, allowed)
                if not prose:
                    raise ValueError("reporter returned no prose")
                if bad:
                    raise _NumberGuardError([t for t, _ in bad])
                verbose_prose = prose
                break
            except _NumberGuardError as exc:
                hint = exc.hint
                note(
                    "verbose_report_guard",
                    {
                        "attempt": attempts,
                        "guard_hint": hint[:400],
                        "stage": "reporting",
                    },
                )
            except Exception as exc:
                hint = _repair_hint(exc)
        if verbose_prose is not None:
            verbose_note = (
                "the number guard caught an invented number in the first draft"
                if attempts == 2
                else ""
            )
        else:
            offending = ""
            if hint:
                offending = f"; last hint: {hint[:200]}"
            limitations.append(
                "verbose report: the reporter model's prose failed the number "
                f"guard or validation twice{offending}; the deterministic "
                "template was used"
            )
            # The report dict baked the limitations in before this stage ran.
            report["limitations"] = sorted(set(limitations))
        template_reason = (
            None if verbose_prose is not None
            else "the reporter model's prose could not be used safely"
        )
    else:
        template_reason = (
            "no LLM reporter is configured"
            if reporter_fn is None
            else "the critique did not complete; the reporter model only "
            "writes after a completed critique"
        )
    llm_wrote = verbose_prose is not None
    if verbose_prose is None:
        verbose_prose = _template_verbose_report(brief, report)
    report["verbose"] = {
        "prose": verbose_prose,
        # Did the model's prose reach the page? Verified BEFORE the template
        # was substituted, so a guarded-out draft cannot be mislabelled.
        "llm_written": llm_wrote,
        "attempts": attempts,
        "template_fallback": template_reason is not None,
        "template_reason": template_reason,
        "note": verbose_note,
    }

    terminal = RunState.COMPLETED_WITH_LIMITATIONS if limitations else RunState.COMPLETED
    move(terminal)
    report["state"] = terminal.value
    _close_stage()
    report["stages"] = stage_seconds

    # The critic findings are stored with the rest of the run (the evidence
    # and the scores were already written when their stage completed).
    for ordinal, finding in enumerate(findings):
        add_critic_finding(engine, run_id, finding, ordinal=ordinal)
    set_revision_count(engine, run_id, revision_count)
    update_run_state(engine, run_id, terminal.value, final_report_json=report)
    bundle = get_run_bundle(engine, run_id)
    return {"run_id": run_id, "state": terminal.value, "report": report, "persisted": bundle["run"]["state"]}


__all__ = ["run_decision"]
