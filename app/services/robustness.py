"""Sensitivity analysis (docs/architecture.md Stage 5, SCOPE.md G4).

Deterministic, seeded, offline: replays the decision engine over sampled
weight vectors on the run's frozen evidence. No LLM tokens, no Qloo calls.
Output phrasing is fixed: "Top-ranked in X% of tested preference scenarios."
Never a probability of success (AGENTS.md hard rule 9).
"""

from __future__ import annotations

import random
from typing import Any

from app.schemas.brief import HardConstraint, Weights
from app.services.decision_engine import SCORING_VERSION, score_concepts

MAX_SAMPLES = 1000
DEFAULT_SEED = 20261016
DEFAULT_HALF_WIDTH = 0.20

PERMITTED_PHRASE = "Top-ranked in {pct:.0%} of tested preference scenarios."
# A tie is stated in its own words (human decision, 2026-10-22): claiming
# "top-ranked" for concepts that are level would overstate the difference.
TIE_PERMITTED_PHRASE = "Tied with {others} in {pct:.0%} of tested preference scenarios."
# Two concepts count as tied within this many points of each other.
TIE_EPSILON_POINTS = 0.5


def sample_weight_vectors(
    base: dict[str, float],
    n: int,
    seed: int = DEFAULT_SEED,
    half_width: float = DEFAULT_HALF_WIDTH,
) -> list[dict[str, float]]:
    """Rejection-sample valid weight vectors in a box around the base weights.

    Box per criterion: [max(0, b-h), min(1, b+h)]. Draw uniform, normalize to
    sum 1, keep iff normalized values stay in their boxes. Deterministic in
    `seed`. Hard cap MAX_SAMPLES.
    """
    n = min(n, MAX_SAMPLES)
    keys = sorted(base)
    lo = {k: max(0.0, base[k] - half_width) for k in keys}
    hi = {k: min(1.0, base[k] + half_width) for k in keys}
    rng = random.Random(seed)
    out: list[dict[str, float]] = []
    attempts = 0
    while len(out) < n and attempts < n * 100 + 1000:
        attempts += 1
        draw = {k: rng.uniform(lo[k], hi[k]) for k in keys}
        total = sum(draw.values())
        if total <= 0:
            continue
        vec = {k: draw[k] / total for k in keys}
        if all(lo[k] - 1e-9 <= vec[k] <= hi[k] + 1e-9 for k in keys):
            out.append(vec)
    return out


def named_scenario_vectors() -> list[dict[str, float]]:
    """Fallback when sampling is unavailable: three fixed scenarios."""
    return [
        {"C1": 0.55, "C2": 0.15, "C3": 0.15, "C5": 0.15},  # affinity-first
        {"C1": 0.15, "C2": 0.55, "C3": 0.15, "C5": 0.15},  # differentiation-first
        {"C1": 0.25, "C2": 0.25, "C3": 0.25, "C5": 0.25},  # balanced
    ]


def _weights_from(vec: dict[str, float]) -> Weights:
    return Weights(c1=vec["C1"], c2=vec["C2"], c3=vec["C3"], c5=vec["C5"])


def analyze_sensitivity(
    concept_ids: list[str],
    raw_values: dict[str, dict[str, float | None]],
    hard_constraints: list[HardConstraint],
    concept_attributes: dict[str, dict[str, str]],
    base_weights: Weights,
    scoring_version: str = SCORING_VERSION,
    seed: int = DEFAULT_SEED,
    n: int = MAX_SAMPLES,
    use_named_fallback: bool = False,
) -> dict[str, Any]:
    """Replay scoring over sampled (or named) weight vectors. Deterministic."""
    base = base_weights.as_dict()
    if use_named_fallback:
        vectors = named_scenario_vectors()
        method = "named-scenarios"
    else:
        vectors = sample_weight_vectors(base, n=n, seed=seed)
        method = "seeded-sampling"

    wins: dict[str, int] = {cid: 0 for cid in concept_ids}
    ties: dict[str, int] = {cid: 0 for cid in concept_ids}
    tie_with: dict[str, set[str]] = {cid: set() for cid in concept_ids}
    tie_scenarios = 0
    ranks: dict[str, list[int]] = {cid: [] for cid in concept_ids}
    flip_votes: dict[str, int] = {c: 0 for c in ("C1", "C2", "C3", "C5")}
    base_winner: str | None = None

    base_scores = score_concepts(
        concept_ids, base_weights, raw_values, hard_constraints, scoring_version, concept_attributes
    )
    for s in base_scores:
        if s.rank == 1:
            base_winner = s.concept_id

    for vec in vectors:
        scored = score_concepts(
            concept_ids, _weights_from(vec), raw_values, hard_constraints, scoring_version, concept_attributes
        )
        winner = next((s for s in scored if s.rank == 1), None)
        for s in scored:
            if s.rank is not None:
                ranks[s.concept_id].append(s.rank)
        if winner is None:
            continue
        # Is the leader level with another concept in THIS scenario?
        totals = sorted(
            (
                (float(s.weighted_total), s.concept_id)
                for s in scored
                if s.rank is not None and s.weighted_total is not None
            ),
            reverse=True,
        )
        level = (
            [cid for total, cid in totals if abs(totals[0][0] - total) <= TIE_EPSILON_POINTS]
            if len(totals) > 1
            else [winner.concept_id]
        )
        if len(level) > 1:
            tie_scenarios += 1
            for cid in level:
                ties[cid] += 1
                tie_with[cid].update(c for c in level if c != cid)
        else:
            wins[winner.concept_id] += 1
        if winner.concept_id != base_winner:
            dev = {c: abs(vec[c] - base[c]) for c in base}
            pivotal = max(dev, key=lambda c: dev[c])
            flip_votes[pivotal] += 1

    total = len(vectors)
    frequency = {cid: (wins[cid] / total if total else 0.0) for cid in concept_ids}
    tie_frequency = {cid: (ties[cid] / total if total else 0.0) for cid in concept_ids}
    rank_range = {
        cid: ([min(ranks[cid]), max(ranks[cid])] if ranks[cid] else [None, None])
        for cid in concept_ids
    }
    pivotal = max(flip_votes, key=lambda c: flip_votes[c]) if sum(flip_votes.values()) else None
    tie_statements = {
        cid: TIE_PERMITTED_PHRASE.format(
            others=", ".join(sorted(tie_with[cid])),
            pct=tie_frequency[cid],
        )
        for cid in concept_ids
        if ties[cid] > 0
    }
    return {
        "method": method,
        "seed": seed if method == "seeded-sampling" else None,
        "scenarios_tested": total,
        "base_winner": base_winner,
        "top_rank_frequency": frequency,
        "statements": {
            cid: PERMITTED_PHRASE.format(pct=frequency[cid]) for cid in concept_ids
        },
        "tie_frequency": tie_frequency,
        "tie_statements": tie_statements,
        # How many scenarios ended in a tie at all (a pairwise tie counts
        # once, so wins + tie scenarios cover every scenario exactly).
        "tie_scenarios": tie_scenarios,
        "tie_scenario_fraction": (tie_scenarios / total if total else 0.0),
        "rank_range": rank_range,
        "pivotal_criterion": pivotal,
        "scoring_version": scoring_version,
    }


__all__ = [
    "MAX_SAMPLES",
    "DEFAULT_SEED",
    "PERMITTED_PHRASE",
    "sample_weight_vectors",
    "named_scenario_vectors",
    "analyze_sensitivity",
]
