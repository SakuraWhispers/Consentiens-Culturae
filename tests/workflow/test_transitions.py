"""Tests for the workflow state machine (written with the implementation; the
transition table is the contract these tests pin down)."""

import pytest

from app.workflow.states import RunState, TERMINAL_STATES
from app.workflow.transitions import (
    IllegalTransitionError,
    allowed_targets,
    can_transition,
    is_terminal,
    transition,
)

HAPPY_PATH = [
    RunState.CREATED,
    RunState.VALIDATING_INPUT,
    RunState.RETRIEVING_EVIDENCE,
    RunState.NORMALIZING_EVIDENCE,
    RunState.SCORING,
    RunState.DRAFTING_EXPLANATION,
    RunState.CRITIC_REVIEW,
    RunState.FINAL_VALIDATION,
    RunState.ROBUSTNESS_ANALYSIS,
    RunState.COMPLETED,
]

REVISION_PATH = [
    RunState.CREATED,
    RunState.VALIDATING_INPUT,
    RunState.RETRIEVING_EVIDENCE,
    RunState.NORMALIZING_EVIDENCE,
    RunState.SCORING,
    RunState.DRAFTING_EXPLANATION,
    RunState.CRITIC_REVIEW,
    RunState.REVISING,
    RunState.FINAL_VALIDATION,
    RunState.ROBUSTNESS_ANALYSIS,
    RunState.COMPLETED_WITH_LIMITATIONS,
]


class TestHappyPath:
    @pytest.mark.parametrize("path", [HAPPY_PATH, REVISION_PATH])
    def test_full_path_is_legal(self, path):
        for current, target in zip(path, path[1:]):
            assert transition(current, target) == target


class TestIllegalTransitions:
    def test_cannot_skip_evidence_retrieval(self):
        with pytest.raises(IllegalTransitionError):
            transition(RunState.CREATED, RunState.SCORING)

    def test_cannot_jump_to_completed(self):
        with pytest.raises(IllegalTransitionError):
            transition(RunState.RETRIEVING_EVIDENCE, RunState.COMPLETED)

    def test_revision_only_from_critic_review(self):
        with pytest.raises(IllegalTransitionError):
            transition(RunState.DRAFTING_EXPLANATION, RunState.REVISING)

    def test_self_transitions_are_illegal(self):
        for state in RunState:
            with pytest.raises(IllegalTransitionError):
                transition(state, state)

    @pytest.mark.parametrize(
        "terminal",
        [
            RunState.COMPLETED,
            RunState.COMPLETED_WITH_LIMITATIONS,
            RunState.FAILED_TERMINAL,
        ],
    )
    def test_terminal_states_have_no_outgoing_moves(self, terminal):
        assert is_terminal(terminal)
        assert allowed_targets(terminal) == frozenset()
        assert not can_transition(terminal, RunState.VALIDATING_INPUT)


class TestRetryableFailure:
    def test_retryable_failure_can_resume_retrieval(self):
        assert transition(RunState.FAILED_RETRYABLE, RunState.RETRIEVING_EVIDENCE) == RunState.RETRIEVING_EVIDENCE
        assert not is_terminal(RunState.FAILED_RETRYABLE)

    def test_retryable_cannot_skip_to_scoring(self):
        with pytest.raises(IllegalTransitionError):
            transition(RunState.FAILED_RETRYABLE, RunState.SCORING)


class TestEveryStateIsInTable:
    def test_no_state_is_missing_from_the_transition_table(self):
        # exhaustive walk: every state must appear as a key and every listed
        # target must also be a key (no dangling pointers)
        from app.workflow.transitions import _ALLOWED

        assert set(_ALLOWED) == set(RunState)
        for targets in _ALLOWED.values():
            for target in targets:
                assert isinstance(target, RunState)
        assert TERMINAL_STATES == {
            RunState.COMPLETED,
            RunState.COMPLETED_WITH_LIMITATIONS,
            RunState.FAILED_TERMINAL,
        }
