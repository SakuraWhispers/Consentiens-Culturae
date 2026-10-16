"""Analyst + critic wrappers (G3): prompt, call, schema-validate.

Validation failures raise (pydantic ValidationError or AgentLLMError); the
coordinator retries once, then falls back to the deterministic template.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.agents.llm_client import complete_json
from app.agents.prompts import ANALYST_SYSTEM, CRITIC_SYSTEM, RESEARCHER_SYSTEM, REVISION_SYSTEM
from app.agents.researcher import validate_plan
from app.agents.schemas import AnalysisDraft, CriticOutput, RetrievalPlan


def draft_plan_llm(
    api_key: str, model: str, concept_names: list[str], tag_urn: str | None,
    timeout: float = 30.0, client: httpx.Client | None = None,
) -> RetrievalPlan:
    parsed = complete_json(
        api_key, model, RESEARCHER_SYSTEM,
        {"concepts": concept_names, "tag_urn": tag_urn, "max_calls": 10},
        timeout, client,
    )
    return validate_plan(RetrievalPlan(**parsed))


def draft_claims_llm(
    api_key: str, model: str, score_summary: dict[str, Any],
    evidence_summary: dict[str, Any], limitations: list[str], weights: dict[str, float],
    timeout: float = 30.0, client: httpx.Client | None = None,
) -> AnalysisDraft:
    parsed = complete_json(
        api_key, model, ANALYST_SYSTEM,
        {"scores": score_summary, "evidence": evidence_summary,
         "limitations": limitations, "weights": weights},
        timeout, client,
    )
    return AnalysisDraft(**parsed)


def review_claims_llm(
    api_key: str, model: str, claims: list[dict[str, Any]],
    score_summary: dict[str, Any], evidence_ids: list[str],
    timeout: float = 30.0, client: httpx.Client | None = None,
) -> CriticOutput:
    parsed = complete_json(
        api_key, model, CRITIC_SYSTEM,
        {"claims": claims, "scores": score_summary, "known_evidence_ids": evidence_ids},
        timeout, client,
    )
    return CriticOutput(**parsed)


def revise_claims_llm(
    api_key: str, model: str, claims: list[dict[str, Any]], findings: list[dict[str, Any]],
    timeout: float = 30.0, client: httpx.Client | None = None,
) -> AnalysisDraft:
    parsed = complete_json(
        api_key, model, REVISION_SYSTEM,
        {"claims": claims, "findings": findings},
        timeout, client,
    )
    return AnalysisDraft(**parsed)


__all__ = ["draft_plan_llm", "draft_claims_llm", "review_claims_llm", "revise_claims_llm"]
