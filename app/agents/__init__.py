"""Agent role wrappers (G3). Thin prompt-and-schema layers, not services."""

from app.agents.analyst import (
    draft_claims_llm,
    draft_plan_llm,
    review_claims_llm,
    revise_claims_llm,
)
from app.agents.llm_client import AgentLLMError, complete_json
from app.agents.researcher import (
    PlanRejectedError,
    researcher_fallback,
    salvage_calls,
    validate_call,
    validate_plan,
)
from app.agents.schemas import (
    AgentOutput,
    AnalysisDraft,
    CriticOutput,
    RetrievalPlan,
    RichClaim,
)

__all__ = [
    "AgentLLMError",
    "AgentOutput",
    "PlanRejectedError",
    "complete_json",
    "draft_claims_llm",
    "draft_plan_llm",
    "review_claims_llm",
    "revise_claims_llm",
    "researcher_fallback",
    "salvage_calls",
    "validate_call",
    "validate_plan",
    "AnalysisDraft",
    "CriticOutput",
    "RetrievalPlan",
    "RichClaim",
]
