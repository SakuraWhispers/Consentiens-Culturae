"""Robustness tests: seeded sampling, determinism, gates, fallback. Offline."""

from __future__ import annotations

from app.schemas.brief import Weights
from app.services.robustness import (
    DEFAULT_SEED,
    MAX_SAMPLES,
    analyze_sensitivity,
    named_scenario_vectors,
    sample_weight_vectors,
)


def _weights(**kw) -> Weights:
    base = {"c1": 0.35, "c2": 0.20, "c3": 0.25, "c5": 0.20}
    base.update(kw)
    return Weights(**base)


def _raw() -> dict[str, dict[str, float | None]]:
    return {
        # A wins on C1, B wins on C2/C3: weight shifts flip the winner.
        "A": {"C1": 0.9, "C2": 0.1, "C3": 0.5, "C5": 0.6},
        "B": {"C1": 0.1, "C2": 0.9, "C3": 0.8, "C5": 0.6},
        "C": {"C1": 0.4, "C2": 0.4, "C3": 0.4, "C5": 0.4},
    }


def test_sampling_respects_bounds_and_seed() -> None:
    base = _weights()
    a = sample_weight_vectors(base.as_dict(), n=200, seed=DEFAULT_SEED)
    b = sample_weight_vectors(base.as_dict(), n=200, seed=DEFAULT_SEED)
    assert a == b
    assert len(a) == 200
    for vec in a:
        assert abs(sum(vec.values()) - 1.0) < 1e-9
        for k, v in vec.items():
            assert 0.0 <= v <= 1.0


def test_analysis_deterministic_with_frequencies_and_range() -> None:
    base = _weights()
    one = analyze_sensitivity(["A", "B", "C"], _raw(), [], {}, base, seed=7, n=200)
    two = analyze_sensitivity(["A", "B", "C"], _raw(), [], {}, base, seed=7, n=200)
    assert one == two
    assert one["scenarios_tested"] == 200
    assert one["seed"] == 7
    total = sum(one["top_rank_frequency"].values())
    assert abs(total - 1.0) < 1e-9
    assert set(one["rank_range"]) == {"A", "B", "C"}
    assert one["top_rank_frequency"]["A"] > 0
    assert one["top_rank_frequency"]["B"] > 0


def test_infeasible_concept_never_top_ranked() -> None:
    from app.schemas.brief import HardConstraint

    base = _weights()
    out = analyze_sensitivity(
        ["A", "B", "C"],
        _raw(),
        [HardConstraint(attribute="material", value="recycled")],
        {"A": {"material": "recycled"}, "B": {"material": "plastic"}, "C": {"material": "recycled"}},
        base,
        seed=7,
        n=100,
    )
    assert out["top_rank_frequency"].get("B", 0.0) == 0.0


def test_pivotal_criterion_identified() -> None:
    base = _weights()
    out = analyze_sensitivity(["A", "B", "C"], _raw(), [], {}, base, seed=7, n=300)
    assert out["pivotal_criterion"] in ("C1", "C2", "C3", "C5", None)
    # C1-heavy vectors favor A, C2-heavy favor B: a flip must occur.
    assert out["pivotal_criterion"] in ("C1", "C2")


def test_named_fallback_has_three_scenarios() -> None:
    vecs = named_scenario_vectors()
    assert len(vecs) == 3
    for vec in vecs:
        assert abs(sum(vec.values()) - 1.0) < 1e-9
    base = _weights()
    out = analyze_sensitivity(["A", "B", "C"], _raw(), [], {}, base, use_named_fallback=True)
    assert out["method"] == "named-scenarios"
    assert out["scenarios_tested"] == 3


def test_sample_cap_enforced() -> None:
    assert MAX_SAMPLES == 1000
    base = _weights()
    vecs = sample_weight_vectors(base.as_dict(), n=5000, seed=1)
    assert len(vecs) == 1000
