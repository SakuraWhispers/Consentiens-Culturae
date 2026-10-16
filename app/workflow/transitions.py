"""Legal state transitions (docs/architecture.md section 4).

The coordinator is the only component allowed to move a run between states,
and only through check_transition / transition, which enforce this table.
"""

from collections.abc import Mapping

from app.workflow.states import TERMINAL_STATES, RunState


class IllegalTransitionError(RuntimeError):
    """Raised when the coordinator attempts a move the state table forbids."""


_ALLOWED: Mapping[RunState, frozenset[RunState]] = {
    RunState.CREATED: frozenset({RunState.VALIDATING_INPUT}),
    RunState.VALIDATING_INPUT: frozenset(
        {RunState.RETRIEVING_EVIDENCE, RunState.FAILED_TERMINAL}
    ),
    RunState.RETRIEVING_EVIDENCE: frozenset(
        {RunState.NORMALIZING_EVIDENCE, RunState.FAILED_RETRYABLE, RunState.FAILED_TERMINAL}
    ),
    RunState.NORMALIZING_EVIDENCE: frozenset(
        {RunState.SCORING, RunState.FAILED_TERMINAL}
    ),
    RunState.SCORING: frozenset(
        {RunState.DRAFTING_EXPLANATION, RunState.FAILED_RETRYABLE}
    ),
    RunState.DRAFTING_EXPLANATION: frozenset(
        {RunState.CRITIC_REVIEW, RunState.FAILED_RETRYABLE}
    ),
    RunState.CRITIC_REVIEW: frozenset(
        {RunState.REVISING, RunState.FINAL_VALIDATION, RunState.FAILED_RETRYABLE}
    ),
    RunState.REVISING: frozenset(
        {RunState.FINAL_VALIDATION, RunState.FAILED_RETRYABLE}
    ),
    RunState.FINAL_VALIDATION: frozenset(
        {RunState.ROBUSTNESS_ANALYSIS, RunState.FAILED_RETRYABLE}
    ),
    RunState.ROBUSTNESS_ANALYSIS: frozenset(
        {
            RunState.COMPLETED,
            RunState.COMPLETED_WITH_LIMITATIONS,
            RunState.FAILED_RETRYABLE,
        }
    ),
    # Terminal states have no outgoing moves...
    RunState.COMPLETED: frozenset(),
    RunState.COMPLETED_WITH_LIMITATIONS: frozenset(),
    RunState.FAILED_TERMINAL: frozenset(),
    # ...except a retryable failure can resume evidence retrieval.
    RunState.FAILED_RETRYABLE: frozenset({RunState.RETRIEVING_EVIDENCE}),
}


def can_transition(current: RunState, target: RunState) -> bool:
    return target in _ALLOWED[current]


def allowed_targets(current: RunState) -> frozenset[RunState]:
    return _ALLOWED[current]


def transition(current: RunState, target: RunState) -> RunState:
    """Return the new state or raise IllegalTransitionError."""
    if current is target:
        raise IllegalTransitionError(f"self-transition {current.name} is illegal")
    if not can_transition(current, target):
        raise IllegalTransitionError(f"illegal transition {current.name} -> {target.name}")
    return target


def is_terminal(state: RunState) -> bool:
    return state in TERMINAL_STATES
