"""Deterministic coordinator (docs/architecture.md sections 2 and 4).

The only component that moves a run between states, and only through the
transition table. G2 path: brief -> retrieval plan -> evidence -> normalize ->
extract -> score -> template explanation -> deterministic critic -> validate ->
report. LLM stages use deterministic fallbacks (template + rule checks) until
G3 wires the analyst/critic behind a flag. Sensitivity is deferred to G4 and
recorded as a limitation. Code only: no LLM call, no randomness.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import Engine

from app.agents.schemas import ALLOWED_PARAMS, ALLOWLISTED_ENDPOINTS
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
    set_revision_count,
    update_run_state,
)
from app.workflow.states import RunState
from app.workflow.transitions import transition

SCORING_VERSION_DEFAULT = "v0.1"
WORKFLOW_VERSION = "w0.1-g2"
MAX_LIVE_CALLS_PER_RUN = 10


def _move(engine: Engine, run_id: str, seq: int, current: RunState, target: RunState) -> tuple[RunState, int]:
    nxt = transition(current, target)
    seq += 1
    add_workflow_event(engine, run_id, seq, nxt.value, f"enter_{nxt.value.lower()}", {})
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


def _validate_agent_plan(
    plan: list[tuple[str | None, str, dict[str, str]]],
    known_concepts: list[str],
    max_calls: int,
) -> tuple[list[tuple[str | None, str, dict[str, str]]], list[str]]:
    """Code-side enforcement for researcher-proposed plans."""
    limitations: list[str] = []
    kept: list[tuple[str | None, str, dict[str, str]]] = []
    for owner, endpoint, params in plan:
        if endpoint not in ALLOWLISTED_ENDPOINTS:
            limitations.append(f"rejected planned call: endpoint {endpoint!r} not on allowlist")
            continue
        bad = [k for k in params if k not in ALLOWED_PARAMS[endpoint]]
        if bad:
            limitations.append(f"rejected planned call: params {bad} not allowed for {endpoint}")
            continue
        if owner is not None and owner not in known_concepts:
            limitations.append(f"rejected planned call: unknown concept {owner!r}")
            continue
        kept.append((owner, endpoint, params))
    if len(kept) > max_calls:
        limitations.append(f"plan truncated to call budget: {len(kept)} > {max_calls}")
        kept = kept[:max_calls]
    return kept, limitations


_CAUSAL_PHRASES = (
    "will succeed", "will fail", "drives ", "guarantees", "proves ",
    "purchase intent", "will buy", "because of",
)


def _deterministic_critic(
    claims: list[dict[str, Any]], known_ids: set[str]
) -> list[dict[str, Any]]:
    """Rule checks only: unknown evidence IDs, missing evidence, causal phrasing."""
    findings: list[dict[str, Any]] = []
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
                }
            )
        if not claim.get("evidence_ids"):
            findings.append(
                {
                    "issue_code": "MISSING_EVIDENCE",
                    "severity": "minor",
                    "affected_concept_id": claim["concept_id"],
                    "affected_claim_id": claim["claim_id"],
                    "evidence_ids": [],
                    "explanation": "no available evidence backs this concept's claim",
                    "suggested_action": "qualify",
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
    """Hard invariants for critic output: closed issue codes, known concepts."""
    from app.agents.schemas import ISSUE_CODES

    for finding in findings:
        if finding.get("issue_code") not in ISSUE_CODES:
            raise ValueError(f"unknown issue code {finding.get('issue_code')!r}")
        if finding.get("affected_concept_id") not in known_concepts:
            raise ValueError(f"finding targets unknown concept {finding.get('affected_concept_id')!r}")
        if finding.get("suggested_action") not in ("remove", "qualify", "revise_wording"):
            raise ValueError(f"unknown suggested action {finding.get('suggested_action')!r}")
    return findings


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
) -> dict[str, Any]:
    """Injectable agent hooks (G3): each defaults to the deterministic path.

    researcher_fn(names, tag_urn) -> plan list; analyst_fn(scores, evidence,
    limitations, weights) -> claim dicts; critic_fn(claims, scores, known_ids)
    -> finding dicts; revise_fn(claims, findings) -> revised claim dicts.
    Any hook failure is retried once, then replaced by the deterministic
    fallback with a recorded limitation.
    """
    run_id = create_run(
        engine,
        input_json=brief.model_dump(),
        scoring_version=scoring_version,
        workflow_version=workflow_version,
    )
    seq = 0
    state = RunState.CREATED
    limitations: list[str] = []
    live_calls = 0

    def move(target: RunState) -> None:
        nonlocal state, seq
        state, seq = _move(engine, run_id, seq, state, target)

    move(RunState.VALIDATING_INPUT)
    move(RunState.RETRIEVING_EVIDENCE)

    records_by_concept: dict[str, list[EvidenceRecord]] = {c.concept_id: [] for c in brief.concepts}
    fixture_flags: list[bool] = []
    concept_names = {c.concept_id: c.name for c in brief.concepts}
    concept_ids = [c.concept_id for c in brief.concepts]
    if researcher_fn is not None:
        try:
            proposed = researcher_fn(
                [c.name for c in brief.concepts], getattr(source, "tag_urn", None)
            )
            calls, plan_limits = _validate_agent_plan(proposed, concept_ids, max_live_calls)
            limitations.extend(plan_limits)
            if not calls:
                calls = _plan_calls(brief, source)
                limitations.append("agent plan fully rejected; deterministic plan used")
        except Exception as exc:
            calls = _plan_calls(brief, source)
            limitations.append(f"researcher plan failed ({type(exc).__name__}); deterministic plan used")
    else:
        calls = _plan_calls(brief, source)
    for owner_id, endpoint, params in calls:
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

    move(RunState.DRAFTING_EXPLANATION)
    by_id = {s.concept_id: s for s in scores}
    known_ids = {r.evidence_id for recs in records_by_concept.values() for r in recs}

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
        cid: {"available": sum(1 for r in recs if r.coverage_status == "available"), "total": len(recs)}
        for cid, recs in records_by_concept.items()
    }
    if analyst_fn is not None:
        claims = None
        for _ in range(2):
            try:
                candidate = analyst_fn(
                    score_summary, evidence_summary, limitations, brief.weights.as_dict()
                )
                claims = _validate_claims(
                    [dict(c) for c in candidate], concept_ids, known_ids
                )
                break
            except Exception:
                claims = None
        if claims is None:
            analyst_llm = False
            limitations.append("analyst LLM output invalid twice; template explanation used")
            claims = _template_claims()
    else:
        claims = _template_claims()

    move(RunState.CRITIC_REVIEW)
    critic_llm = critic_fn is not None
    if critic_fn is not None:
        findings = None
        for _ in range(2):
            try:
                candidate = critic_fn(claims, score_summary, sorted(known_ids))
                findings = _validate_critic_output([dict(f) for f in candidate], concept_ids)
                break
            except Exception:
                findings = None
        if findings is None:
            critic_llm = False
            limitations.append("critic LLM output invalid twice; deterministic checks used")
            findings = _deterministic_critic(claims, known_ids)
    else:
        findings = _deterministic_critic(claims, known_ids)

    revision_count = 0
    revisable = [f for f in findings if f.get("suggested_action") == "revise_wording"]
    if revisable and revise_fn is not None:
        move(RunState.REVISING)
        revised = None
        for _ in range(2):
            try:
                candidate = revise_fn(claims, findings)
                revised = _validate_claims(
                    [dict(c) for c in candidate], concept_ids, known_ids
                )
                break
            except Exception:
                revised = None
        if revised is not None:
            claims = revised
            revision_count = 1
            findings = findings + _deterministic_critic(claims, known_ids)
        else:
            limitations.append("revision failed twice; original claims kept and qualified")
            for claim in claims:
                claim["qualified"] = True
    elif revisable:
        for claim in claims:
            claim["qualified"] = True

    move(RunState.FINAL_VALIDATION)
    winner = next((s for s in scores if s.rank == 1), None)
    fixture_mode = bool(fixture_flags) and all(fixture_flags)

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
    terminal = RunState.COMPLETED_WITH_LIMITATIONS if limitations else RunState.COMPLETED
    move(terminal)
    report["state"] = terminal.value

    for recs in records_by_concept.values():
        if recs:
            add_evidence_records(engine, run_id, [r.model_dump(exclude={"retrieved_at"}) for r in recs])
    for s in scores:
        add_score_snapshot(
            engine,
            run_id,
            s.concept_id,
            {"status": s.status, "rank": s.rank, "weighted_total": s.weighted_total, "coverage": s.coverage},
            scoring_version,
        )
    for finding in findings:
        add_critic_finding(engine, run_id, finding)
    set_revision_count(engine, run_id, revision_count)
    update_run_state(engine, run_id, terminal.value, final_report_json=report)
    bundle = get_run_bundle(engine, run_id)
    return {"run_id": run_id, "state": terminal.value, "report": report, "persisted": bundle["run"]["state"]}


__all__ = ["run_decision"]
