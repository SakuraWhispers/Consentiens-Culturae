"""Pydantic v2 contracts for Consentiens-Culturae. Every API input and output lives here."""

from app.schemas.brief import DEMO_CATEGORY, DecisionBrief, HardConstraint, Weights
from app.schemas.concept import ConceptInput
from app.schemas.evidence import (
    CoverageStatus,
    ErrorCode,
    EvidenceRecord,
    MatchQuality,
    SourceKind,
)
from app.schemas.scoring import (
    ConceptScore,
    CriterionId,
    CriterionScore,
    ScoreStatus,
)

__all__ = [
    "DEMO_CATEGORY",
    "DecisionBrief",
    "HardConstraint",
    "Weights",
    "ConceptInput",
    "EvidenceRecord",
    "CoverageStatus",
    "MatchQuality",
    "SourceKind",
    "ErrorCode",
    "CriterionId",
    "CriterionScore",
    "ConceptScore",
    "ScoreStatus",
]
