"""Scientific, offline tests for the deterministic decision engine.

These tests were written before the engine (AGENTS.md working rule).
No Qloo data involved: criterion values are synthetic numbers the tests control.
"""

import pytest
from pydantic import ValidationError

from app.schemas.brief import HardConstraint, Weights
from app.schemas.scoring import ConceptScore
from app.services.decision_engine import (
    min_max_normalize,
    score_concepts,
)


def weights(c1=0.3, c2=0.2, c3=0.2, c4=0.1, c5=0.2) -> Weights:
    return Weights(c1=c1, c2=c2, c3=c3, c4=c4, c5=c5)


def raw_values(**overrides) -> dict[str, dict[str, float | None]]:
    """Three concepts with distinct, known raw values (arbitrary scales)."""
    base = {
        "A": {"C1": 80.0, "C2": 10.0, "C3": 20.0, "C5": 0.8},
        "B": {"C1": 40.0, "C2": 5.0, "C3": 40.0, "C5": 0.5},
        "C": {"C1": 60.0, "C2": 15.0, "C3": 30.0, "C5": 0.2},
    }
    for concept_id, patch in overrides.items():
        base[concept_id].update(patch)
    return base


class TestWeightValidation:
    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValidationError):
            weights(c1=0.5, c2=0.5, c3=0.5, c4=0.1, c5=0.2)

    def test_negative_weight_rejected(self):
        with pytest.raises(ValidationError):
            weights(c2=-0.2)

    def test_tolerance_accepts_rounding_drift(self):
        w = Weights(c1=0.3, c2=0.2, c3=0.2, c4=0.1, c5=0.2)
        assert abs(sum(w.as_dict().values()) - 1.0) <= 1e-3


class TestNormalization:
    def test_min_max_known_values(self):
        out = min_max_normalize({"A": 20.0, "B": 40.0, "C": 30.0})
        assert out["A"] == pytest.approx(0.0)
        assert out["B"] == pytest.approx(100.0)
        assert out["C"] == pytest.approx(50.0)

    def test_min_max_all_equal_maps_to_midpoint(self):
        out = min_max_normalize({"A": 7.0, "B": 7.0, "C": 7.0})
        assert all(v == pytest.approx(50.0) for v in out.values())


class TestScoring:
    def test_ranks_by_weighted_total(self):
        results = score_concepts(
            concept_ids=["A", "B", "C"],
            weights=weights(),
            raw_values=raw_values(),
            hard_constraints=[],
            scoring_version="v0.1-test",
        )
        assert all(isinstance(r, ConceptScore) for r in results)
        ranked = {r.concept_id: r for r in results if r.rank is not None}
        assert ranked["A"].rank == 1
        assert ranked["C"].rank == 2  # C beats B on C1-major weights
        assert ranked["B"].rank == 3

    def test_hard_constraint_marks_infeasible_and_never_first(self):
        results = score_concepts(
            concept_ids=["A", "B", "C"],
            weights=weights(),
            raw_values=raw_values(),
            hard_constraints=[
                HardConstraint(attribute="price_band", value="under 10", note=None)
            ],
            concept_attributes={
                "A": {"price_band": "10-20"},
                "B": {"price_band": "under 10"},
                "C": {"price_band": "under 10"},
            },
            scoring_version="v0.1-test",
        )
        by_id = {r.concept_id: r for r in results}
        assert by_id["A"].status == "INFEASIBLE"
        assert by_id["A"].rank is None
        assert "price_band" in by_id["A"].infeasible_reason
        assert by_id["C"].rank == 1 and by_id["B"].rank == 2

    def test_missing_criterion_is_none_and_reweights(self):
        values = raw_values()
        values["A"]["C3"] = None  # missing evidence, not zero
        results = score_concepts(
            concept_ids=["A", "B", "C"],
            weights=weights(),
            raw_values=values,
            hard_constraints=[],
            scoring_version="v0.1-test",
        )
        by_id = {r.concept_id: r for r in results}
        assert by_id["A"].status == "RANKED"  # still rankable
        assert by_id["A"].rank == 1
        c3 = next(cs for cs in by_id["A"].criterion_scores if cs.criterion == "C3")
        assert c3.value is None and c3.raw is None
        # record shows renormalization happened
        applied = [
            cs.weight_applied
            for cs in by_id["A"].criterion_scores
            if cs.criterion in ("C1", "C2", "C5") and cs.value is not None
        ]
        assert sum(applied) == pytest.approx(1.0)

    def test_low_coverage_marks_insufficient_evidence(self):
        values = raw_values()
        values["A"] = {"C1": 80.0, "C2": None, "C3": None, "C5": None}
        results = score_concepts(
            concept_ids=["A", "B", "C"],
            weights=weights(),
            raw_values=values,
            hard_constraints=[],
            scoring_version="v0.1-test",
        )
        by_id = {r.concept_id: r for r in results}
        assert by_id["A"].status == "INSUFFICIENT_EVIDENCE"
        assert by_id["A"].rank is None
        assert insuff_concept := by_id["A"].insufficient_reason
        assert "coverage" in insuff_concept

    def test_tie_broken_by_c1_then_c5_then_id(self):
        values = {
            "A": {"C1": 50.0, "C2": 10.0, "C3": 10.0, "C5": 0.5},
            "B": {"C1": 50.0, "C2": 10.0, "C3": 10.0, "C5": 0.5},
            "C": {"C1": 60.0, "C2": 10.0, "C3": 10.0, "C5": 0.5},
        }
        # zero weights everywhere except C2/C3 which are equal: total ties for A/B
        results = score_concepts(
            concept_ids=["A", "B", "C"],
            weights=weights(c1=1.0, c2=0.0, c3=0.0, c4=0.0, c5=0.0),
            raw_values=values,
            hard_constraints=[],
            scoring_version="v0.1-test",
        )
        # C1 raw equal among A and B -> min_max makes them exactly equal -> rank tie
        by_id = {r.concept_id: r for r in results}
        assert by_id["A"].rank == 1 and by_id["B"].rank == 2
        assert by_id["A"].tie_broken_by is not None
        assert "concept_id" in by_id["A"].tie_broken_by or "C5" in by_id["A"].tie_broken_by

    def test_reproducibility_same_inputs_same_output_ten_runs(self):
        outputs = []
        for _ in range(10):
            outputs.append(
                score_concepts(
                    concept_ids=["A", "B", "C"],
                    weights=weights(),
                    raw_values=raw_values(),
                    hard_constraints=[],
                    scoring_version="v0.1-test",
                )
            )
        first = outputs[0]
        for other in outputs[1:]:
            assert [r.model_dump() for r in first] == [r.model_dump() for r in other]

    def test_unknown_concept_in_raw_values_is_rejected(self):
        values = raw_values()
        values.pop("B")
        with pytest.raises(ValueError):
            score_concepts(
                concept_ids=["A", "B", "C"],
                weights=weights(),
                raw_values=values,
                hard_constraints=[],
                scoring_version="v0.1-test",
            )

    def test_unknown_criterion_key_rejected(self):
        values = raw_values()
        values["A"]["C9"] = 1.0
        with pytest.raises(ValueError):
            score_concepts(
                concept_ids=["A", "B", "C"],
                weights=weights(),
                raw_values=values,
                hard_constraints=[],
                scoring_version="v0.1-test",
            )
