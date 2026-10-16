"""Deterministic scoring engine (docs/architecture.md section 3).

Code only. No LLM call may ever enter this module. No randomness.
Ranks, weights, and scores come from here and only from here (AGENTS.md hard rule 2).

Engine contract: it consumes per-concept RAW criterion values and normalizes
them itself if normalization is needed. Evidence-to-raw-value extraction lives
upstream (evidence_normalizer / researcher) and lands here only as numbers.
"""

from app.config import settings
from app.schemas.brief import CRITERIA, CriterionId, HardConstraint, Weights
from app.schemas.scoring import (
    SOFT_CRITERIA,
    ConceptScore,
    CriterionScore,
    NormalizationMethod,
)

INSUFFICIENT_COVERAGE_THRESHOLD = settings.insufficient_coverage_threshold


class ScoringInputError(ValueError):
    """Raised on malformed scoring input; never silently coerced."""


def min_max_normalize(raw_by_concept: dict[str, float]) -> dict[str, float]:
    """Map raw values to 0-100 with min-max across the run's three concepts.

    Documented behavior (docs/architecture.md section 3.1):
    - min -> 0, max -> 100, others linear in between.
    - all values equal -> 50.0 for each (small differences cannot be exaggerated
      when there is no difference; the midpoint is the neutral choice).
    """
    if not raw_by_concept:
        raise ScoringInputError("min_max_normalize needs at least one concept")
    values = list(raw_by_concept.values())
    lo, hi = min(values), max(values)
    if hi == lo:
        return {cid: 50.0 for cid in raw_by_concept}
    span = hi - lo
    return {cid: (v - lo) / span * 100.0 for cid, v in raw_by_concept.items()}


def fixed_scale_0_100(raw: float) -> float:
    """C5 coverage arrives as a 0-1 share; the fixed scale maps it to 0-100."""
    if not 0.0 <= raw <= 1.0:
        raise ScoringInputError(f"C5 raw value must be a 0-1 share, got {raw}")
    return raw * 100.0


NORMALIZATION_METHODS: dict[str, NormalizationMethod] = {
    "C1": "min_max_across_concepts",
    "C2": "min_max_across_concepts",
    "C3": "min_max_across_concepts",
    "C5": "fixed_scale_0_100",
}


def _check_constraints(
    concept_id: str,
    attributes: dict[str, str],
    constraints: list[HardConstraint],
) -> str | None:
    """Gate check: return a failure reason, or None when feasible."""
    for constraint in constraints:
        actual = attributes.get(constraint.attribute)
        if actual is None:
            return (
                f"hard constraint '{constraint.attribute}' cannot be checked: "
                "concept is missing the attribute"
            )
        if actual != constraint.value:
            return (
                f"hard constraint '{constraint.attribute}' violated: "
                f"concept has '{actual}', constraint requires '{constraint.value}'"
            )
    return None


def score_concepts(
    concept_ids: list[str],
    weights: Weights,
    raw_values: dict[str, dict[str, float | None]],
    hard_constraints: list[HardConstraint],
    scoring_version: str,
    concept_attributes: dict[str, dict[str, str]] | None = None,
) -> list[ConceptScore]:
    """Compute deterministic scores and ranks for exactly the given concepts.

    - Missing evidence is None, never zero (docs/architecture.md section 3.3).
    - The weighted total renormalizes over criteria that are available.
    - C4 is a gate, never part of the weighted sum (section 3.2).
    - INFEASIBLE concepts are never ranked.
    - INSUFFICIENT_EVIDENCE if coverage over soft criteria falls below threshold.
    """
    attributes = concept_attributes or {cid: {} for cid in concept_ids}
    concept_ids = list(dict.fromkeys(concept_ids))

    _validate_inputs(concept_ids, raw_values)

    w = weights.as_dict()
    soft_weights = {c: w[c] for c in SOFT_CRITERIA}

    results: list[ConceptScore] = []
    normalized: dict[str, dict[str, float]] = {}
    missing: dict[str, set[str]] = {}

    # Normalize each criterion across the run's concepts (min-max criteria only).
    for criterion in SOFT_CRITERIA:
        present = {
            cid: raw_values[cid][criterion]
            for cid in concept_ids
            if raw_values[cid].get(criterion) is not None
        }
        method = NORMALIZATION_METHODS[criterion]
        if method == "min_max_across_concepts":
            scaled = min_max_normalize({cid: float(v) for cid, v in present.items()})
        else:
            scaled = {cid: fixed_scale_0_100(float(v)) for cid, v in present.items()}
        for cid in concept_ids:
            if cid in scaled:
                normalized.setdefault(cid, {})[criterion] = scaled[cid]
            else:
                missing.setdefault(cid, set()).add(criterion)

    for cid in concept_ids:
        # 1. Hard-constraint gate.
        infeasible_reason = _check_constraints(cid, attributes.get(cid, {}), hard_constraints)
        if infeasible_reason:
            results.append(
                ConceptScore(
                    concept_id=cid,
                    status="INFEASIBLE",
                    criterion_scores=_criterion_scores(
                        cid, soft_weights, raw_values[cid], normalized.get(cid, {}), missing.get(cid, set())
                    ),
                    infeasible_reason=infeasible_reason,
                )
            )
            continue

        # 2. Coverage gate over soft criteria.
        available = sorted(SOFT_CRITERIA)
        present = [c for c in available if c not in missing.get(cid, set())]
        coverage = len(present) / len(available)
        if coverage < INSUFFICIENT_COVERAGE_THRESHOLD:
            results.append(
                ConceptScore(
                    concept_id=cid,
                    status="INSUFFICIENT_EVIDENCE",
                    criterion_scores=_criterion_scores(
                        cid, soft_weights, raw_values[cid], normalized.get(cid, {}), missing.get(cid, set())
                    ),
                    coverage=coverage,
                    insufficient_reason=(
                        f"evidence coverage {coverage:.0%} is below the "
                        f"{INSUFFICIENT_COVERAGE_THRESHOLD:.0%} threshold; "
                        f"criteria without evidence: {', '.join(sorted(missing.get(cid, set())))}"
                    ),
                )
            )
            continue

        # 3. Reweighted total over available criteria.
        total_weight = sum(soft_weights[c] for c in present)
        renorm = {
            c: (soft_weights[c] / total_weight if total_weight > 0 else 0.0)
            for c in present
        }
        total = sum(renorm[c] * normalized[cid][c] for c in present)

        results.append(
            ConceptScore(
                concept_id=cid,
                status="RANKED",
                criterion_scores=_criterion_scores(
                    cid, soft_weights, raw_values[cid], normalized[cid], missing.get(cid, set()), renorm
                ),
                weighted_total=total,
                coverage=coverage,
            )
        )

    # 4. Ranks over RANKED concepts only. Tie-break: total, then C1, then C5,
    #    then concept_id lexicographic (docs/architecture.md section 3.3).
    ranked = [r for r in results if r.status == "RANKED"]
    ranked.sort(key=lambda r: _rank_key(r, normalized))
    for position, r in enumerate(ranked, start=1):
        r.rank = position

    # Annotate tie breaks: any ranked concept whose pre-tie-break key
    # (-total, -C1, -C5) equals another's was disambiguated by concept_id.
    for r in ranked:
        pre_key = _rank_key(r, normalized)[:-1]
        others = [o for o in ranked if o is not r]
        if any(_rank_key(o, normalized)[:-1] == pre_key for o in others):
            r.tie_broken_by = "total tie: broken by C1, then C5, then concept_id"

    results.sort(key=lambda r: (r.rank is None, r.rank if r.rank is not None else 0, r.concept_id))
    return results


def _validate_inputs(
    concept_ids: list[str],
    raw_values: dict[str, dict[str, float | None]],
) -> None:
    if not concept_ids:
        raise ScoringInputError("at least one concept is required")
    ids_in_values = set(raw_values)
    ids_expected = set(concept_ids)
    if ids_in_values != ids_expected:
        raise ScoringInputError(
            f"raw_values keys {sorted(ids_in_values)} do not match concept ids {sorted(ids_expected)}"
        )
    for cid, values in raw_values.items():
        unknown = set(values) - set(SOFT_CRITERIA)
        if unknown:
            gate_note = (" C4 is gate-only: it has no weight and accepts no numeric input"
                         if "C4" in unknown else "")
            raise ScoringInputError(
                f"unknown criterion keys for {cid}: {sorted(unknown)};"
                f" scoreable criteria: {sorted(SOFT_CRITERIA)}.{gate_note}"
            )


def _criterion_scores(
    concept_id: str,
    soft_weights: dict[str, float],
    raw: dict[str, float | None],
    normalized: dict[str, float],
    missing: set[str],
    renorm: dict[str, float] | None = None,
) -> list[CriterionScore]:
    out = []
    for criterion in sorted(SOFT_CRITERIA):
        present = criterion not in missing
        out.append(
            CriterionScore(
                concept_id=concept_id,
                criterion=criterion,
                raw=raw.get(criterion),
                value=normalized.get(criterion) if present else None,
                method=NORMALIZATION_METHODS[criterion] if present else "none",
                weight_applied=(renorm or {}).get(criterion, 0.0),
                weight_original=soft_weights.get(criterion, 0.0),
            )
        )
    return out


def _total_key(r: ConceptScore, normalized: dict[str, dict[str, float]]) -> float:
    return r.weighted_total if r.weighted_total is not None else float("-inf")


def _rank_key(r: ConceptScore, normalized: dict[str, dict[str, float]]) -> tuple:
    total = _total_key(r, normalized)
    c1 = normalized.get(r.concept_id, {}).get("C1", -1.0) if r.status == "RANKED" else -1.0
    c5 = normalized.get(r.concept_id, {}).get("C5", -1.0) if r.status == "RANKED" else -1.0
    return (-total, -c1, -c5, r.concept_id)
