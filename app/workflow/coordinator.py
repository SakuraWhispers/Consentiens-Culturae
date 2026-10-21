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

from app.agents.researcher import PlanRejectedError, validate_call
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
    A hook may also return an AgentOutput carrier (items + rejection notes +
    a truncated raw payload); a plain list still works.

    Resilience (2026-10-20): each hook is tried at most twice, and the
    second attempt is INFORMED — the validation error is handed back so the
    model can correct itself instead of repeating the same invalid output.
    Invalid individual items are dropped and reported as limitations; the
    deterministic fallback takes over only when an entire stage produced
    nothing usable.
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

    def note(event_type: str, payload: dict[str, Any]) -> None:
        """Record a non-state event (e.g. a rejected agent output) for audit."""
        nonlocal seq
        seq += 1
        add_workflow_event(engine, run_id, seq, state.value, event_type, payload)

    move(RunState.VALIDATING_INPUT)
    move(RunState.RETRIEVING_EVIDENCE)

    records_by_concept: dict[str, list[EvidenceRecord]] = {c.concept_id: [] for c in brief.concepts}
    fixture_flags: list[bool] = []
    concept_names = {c.concept_id: c.name for c in brief.concepts}
    concept_ids = [c.concept_id for c in brief.concepts]
    if researcher_fn is not None:
        # The researcher gets the same two chances as the other agents, and
        # the second one is INFORMED: the rejection reason is handed back so
        # the model can fix the plan instead of repeating it.
        plan_hint: str | None = None
        last_plan_error: Exception | None = None
        calls: list[tuple[str | None, str, dict[str, str]]] = []
        for _attempt in range(2):
            try:
                proposed = _call_hook(
                    researcher_fn,
                    ([c.name for c in brief.concepts], getattr(source, "tag_urn", None)),
                    plan_hint,
                )
            except Exception as exc:
                last_plan_error = exc
                plan_hint = _repair_hint(exc)
                continue
            proposed_calls, agent_rejected, raw_head = _unwrap_hook_output(proposed)
            calls, plan_limits = _validate_agent_plan(
                proposed_calls, concept_ids, max_live_calls
            )
            if calls:
                limitations.extend(plan_limits)
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
        elif not any(endpoint == "insights" for _, endpoint, _ in calls):
            # C3 (market relevance) needs the shared insights call. If the
            # agent's insights call did not survive, use the deterministic
            # one rather than silently losing the market evidence.
            deterministic_insights = [
                call for call in _plan_calls(brief, source) if call[1] == "insights"
            ]
            if deterministic_insights:
                calls.extend(deterministic_insights)
                limitations.append(
                    "researcher plan had no usable insights call; "
                    "deterministic market-insights call added"
                )
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
        last_error: Exception | None = None
        analyst_hint: str | None = None
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
            limitations.append(
                "analyst LLM output invalid twice "
                f"({type(last_error).__name__}: {str(last_error)[:180]}"
                "); template explanation used"
            )
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
                    critic_fn, (claims, score_summary, sorted(known_ids)), critic_hint
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
            findings = _deterministic_critic(claims, known_ids)
    else:
        findings = _deterministic_critic(claims, known_ids)

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
            findings = findings + _deterministic_critic(claims, known_ids)
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
