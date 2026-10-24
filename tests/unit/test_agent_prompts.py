"""Prompt-contract tests: the prompts must STATE the allowed enum values.

Live finding (2026-10-20, run c2b65018…): the critic prompt never listed the
allowed severity values, so the model wrote "medium" and the whole critique
was rejected (4 validation errors, deterministic fallback used). The
researcher prompt never said there is no param named "filter" and never
showed the insights call shape, so the plan was rejected and the deterministic
planner took over.

These tests are the regression guard for the prompt specification. They fail
if a future prompt edit drops an enum list again.
"""

from __future__ import annotations

from app.agents.prompts import (
    ANALYST_SYSTEM,
    CRITIC_SYSTEM,
    RESEARCHER_SYSTEM,
    REVISION_SYSTEM,
)


def test_critic_prompt_lists_allowed_severity_values() -> None:
    for value in ("major", "minor", "info"):
        assert value in CRITIC_SYSTEM
    # The forbidden value is named explicitly so the model cannot reach for it.
    assert "medium" in CRITIC_SYSTEM


def test_critic_prompt_allows_an_empty_findings_list() -> None:
    assert '"findings": []' in CRITIC_SYSTEM


def test_critic_prompt_lists_allowed_suggested_actions() -> None:
    for value in ("remove", "qualify", "revise_wording"):
        assert value in CRITIC_SYSTEM


def test_researcher_prompt_names_the_category_choice() -> None:
    """2026-10-24: the researcher CHOOSES the category; code resolves the tag.
    The prompt must say so and must forbid model-written URNs outright."""
    assert '"category"' in RESEARCHER_SYSTEM
    assert "NEVER write a tag URN" in RESEARCHER_SYSTEM or "urn:" in RESEARCHER_SYSTEM


def test_researcher_prompt_shows_the_call_shape() -> None:
    assert '"endpoint"' in RESEARCHER_SYSTEM
    assert '"params"' in RESEARCHER_SYSTEM


def test_revision_prompt_lists_the_claim_enum_values() -> None:
    # The revision path goes live for the first time once the critic works.
    for value in ("observation", "interpretation", "recommendation"):
        assert value in REVISION_SYSTEM
    for value in ("strong", "moderate", "weak"):
        assert value in REVISION_SYSTEM
    for value in ("high", "medium", "low"):
        assert value in REVISION_SYSTEM


def test_analyst_prompt_keeps_its_existing_enum_contract() -> None:
    for value in ("strong", "moderate", "weak", "high", "medium", "low"):
        assert value in ANALYST_SYSTEM
    assert "observation" in ANALYST_SYSTEM
    assert "recommendation" in ANALYST_SYSTEM


def test_analyst_prompt_states_the_evidence_id_contract() -> None:
    # Changed 2026-10-22: the payload now carries the REAL evidence ids, so
    # the analyst may cite them. The old wording ("MUST be an empty array")
    # is what made the critics flag every claim.
    assert "evidence_ids" in ANALYST_SYSTEM
    assert "MUST be an empty array" not in ANALYST_SYSTEM
    assert "NEVER invent" in ANALYST_SYSTEM
    assert "may leave evidence_ids as []" in ANALYST_SYSTEM


def test_critic_prompt_does_not_flag_an_empty_id_list() -> None:
    assert "An EMPTY list is NOT a defect" in CRITIC_SYSTEM
    assert "known_evidence_ids" in CRITIC_SYSTEM
