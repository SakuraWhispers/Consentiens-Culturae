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


def weights(c1=0.4, c2=0.2, c3=0.2, c5=0.2) -> Weights:
    # C4 is gate-only and has NO weight (human decision 2026-10-15):
    # the user sets weights for the four soft criteria only.
    return Weights(c1=c1, c2=c2, c3=c3, c5=c5)


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
            weights(c1=0.5, c2=0.5, c3=0.5, c5=0.2)  # sums to 1.7

    def test_negative_weight_rejected(self):
        with pytest.raises(ValidationError):
            weights(c2=-0.2)

    def test_c4_field_does_not_exist(self):
        # no hidden input: a payload carrying a C4 weight is rejected at the gate
        with pytest.raises(ValidationError):
            Weights(c1=0.4, c2=0.2, c3=0.2, c5=0.2, c4=0.0)

    def test_weights_cover_only_soft_criteria(self):
        assert set(Weights(c1=0.4, c2=0.2, c3=0.2, c5=0.2).as_dict()) == {"C1", "C2", "C3", "C5"}

    def test_tolerance_accepts_rounding_drift(self):
        w = Weights(c1=0.4, c2=0.2, c3=0.2, c5=0.2)
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

    def test_uncheckable_constraint_ranks_with_a_notice_not_infeasible(self):
        # The 2026-10-23 bug the human hit: a MISSING attribute is not a
        # VIOLATED constraint. Code cannot invent the fact, but the concept
        # still ranks - with a loud, per-concept notice.
        results = score_concepts(
            concept_ids=["A", "B", "C"],
            weights=weights(),
            raw_values=raw_values(),
            hard_constraints=[
                HardConstraint(attribute="material", value="recycled", note=None)
            ],
            concept_attributes={
                "A": {},  # never declared -> cannot be checked
                "B": {"material": "recycled"},
                "C": {"material": "recycled"},
            },
            scoring_version="v0.1-test",
        )
        by_id = {r.concept_id: r for r in results}
        assert by_id["A"].status == "RANKED"
        assert by_id["A"].rank is not None
        assert by_id["A"].infeasible_reason is None
        notice = by_id["A"].constraint_notice
        assert notice is not None and "material" in notice
        # The checkable concepts are flagged clean, not noticed.
        assert by_id["B"].constraint_notice is None
        assert by_id["C"].constraint_notice is None

    def test_a_violation_dominates_a_missing_attribute(self):
        # One violated constraint blocks even when another cannot be checked.
        results = score_concepts(
            concept_ids=["A", "B"],
            weights=weights(),
            raw_values={"A": raw_values()["A"], "B": raw_values()["B"]},
            hard_constraints=[
                HardConstraint(attribute="material", value="recycled", note=None),
                HardConstraint(attribute="price_band", value="under-25", note=None),
            ],
            concept_attributes={
                "A": {"material": "virgin-plastic"},
                "B": {"price_band": "over-100"},
            },
            scoring_version="v0.1-test",
        )
        by_id = {r.concept_id: r for r in results}
        assert by_id["A"].status == "INFEASIBLE"
        assert "material" in by_id["A"].infeasible_reason
        assert by_id["B"].status == "INFEASIBLE"
        assert "price_band" in by_id["B"].infeasible_reason

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
        insuff_concept = by_id["A"].insufficient_reason
        assert insuff_concept
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
            weights=weights(c1=1.0, c2=0.0, c3=0.0, c5=0.0),
            raw_values=values,
            hard_constraints=[],
            scoring_version="v0.1-test",
        )
        # C wins outright (raw 60). A and B tie exactly under min-max and the
        # zero-weighted C5; the tie-break falls through to concept_id lex order.
        by_id = {r.concept_id: r for r in results}
        assert by_id["C"].rank == 1
        assert by_id["A"].rank == 2
        assert by_id["B"].rank == 3
        assert by_id["A"].tie_broken_by is not None
        assert by_id["B"].tie_broken_by is not None
        assert by_id["C"].tie_broken_by is None

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

    def test_c4_in_raw_values_rejected_as_hidden_input(self):
        values = raw_values()
        values["A"]["C4"] = 1.0  # a numeric C4 must be an error, never silently discarded
        with pytest.raises(ValueError) as err:
            score_concepts(
                concept_ids=["A", "B", "C"],
                weights=weights(),
                raw_values=values,
                hard_constraints=[],
                scoring_version="v0.1-test",
            )
        assert "C4" in str(err.value)

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
