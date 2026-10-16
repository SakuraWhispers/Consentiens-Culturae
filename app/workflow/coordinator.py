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

from app.integrations.qloo_adapter import EvidenceSource, FixtureError, QlooPayload
from app.integrations.qloo_client import QlooError
from app.schemas.brief import DecisionBrief
from app.schemas.evidence import EvidenceRecord, make_error_record, stable_evidence_id
from app.services.criterion_extraction import FORMULAS, extract_raw_values
from app.services.decision_engine import score_concepts
from app.services.evidence_normalizer import normalize_response
from app.services.persistence import (
    add_critic_finding,
    add_evidence_records,
    add_score_snapshot,
    add_workflow_event,
    create_run,
    get_run_bundle,
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


def run_decision(
    engine: Engine,
    brief: DecisionBrief,
    source: EvidenceSource,
    scoring_version: str = SCORING_VERSION_DEFAULT,
    workflow_version: str = WORKFLOW_VERSION,
    max_live_calls: int = MAX_LIVE_CALLS_PER_RUN,
) -> dict[str, Any]:
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
    for owner_id, endpoint, params in _plan_calls(brief, source):
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
    move(RunState.SCORING)

    raw_values, diagnostics = extract_raw_values(records_by_concept)
    concept_ids = [c.concept_id for c in brief.concepts]
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
    claims: list[dict[str, Any]] = []
    for concept in brief.concepts:
        s = by_id[concept.concept_id]
        usable_ids = [r.evidence_id for r in records_by_concept[concept.concept_id] if r.coverage_status == "available"]
        rank_text = f"rank {s.rank}" if s.rank is not None else f"status {s.status}"
        claims.append(
            {
                "claim_id": f"claim-{concept.concept_id}",
                "concept_id": concept.concept_id,
                "claim_type": "observation",
                "strength": "moderate" if usable_ids else "weak",
                "text": (
                    f"{concept.name} ({rank_text}, "
                    f"total {s.weighted_total if s.weighted_total is not None else 'n/a'}): "
                    f"{len(usable_ids)} of {len(records_by_concept[concept.concept_id])} evidence records available."
                ),
                "evidence_ids": usable_ids,
                "score_fields": [f"{concept.concept_id}.weighted_total", f"{concept.concept_id}.rank"],
            }
        )

    move(RunState.CRITIC_REVIEW)
    known_ids = {r.evidence_id for recs in records_by_concept.values() for r in recs}
    findings: list[dict[str, Any]] = []
    for claim in claims:
        missing = [eid for eid in claim["evidence_ids"] if eid not in known_ids]
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
        if not claim["evidence_ids"]:
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

    move(RunState.FINAL_VALIDATION)
    winner = next((s for s in scores if s.rank == 1), None)
    limitations.append("sensitivity analysis deferred to G4")
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
        "explanation_template": True,
        "llm_written": False,
        "sensitivity": {"status": "deferred-to-G4"},
        "disclaimer": "Early screening aid. Not a demand forecast.",
    }

    move(RunState.ROBUSTNESS_ANALYSIS)
    terminal = RunState.COMPLETED_WITH_LIMITATIONS if report["limitations"] else RunState.COMPLETED
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
    update_run_state(engine, run_id, terminal.value, final_report_json=report)
    bundle = get_run_bundle(engine, run_id)
    return {"run_id": run_id, "state": terminal.value, "report": report, "persisted": bundle["run"]["state"]}


__all__ = ["run_decision"]
