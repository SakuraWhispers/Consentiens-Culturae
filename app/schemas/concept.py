"""A competing product concept. Exactly 3 per run, unique concept_id."""

from pydantic import BaseModel, Field, field_validator


class ConceptInput(BaseModel):
    concept_id: str = Field(min_length=1, max_length=10)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    # Free-form attribute map used for hard-constraint checks and (later) C2 overlap.
    attributes: dict[str, str] = Field(default_factory=dict)

    @field_validator("concept_id")
    @classmethod
    def _no_whitespace(cls, v: str) -> str:
        if v != v.strip() or not v:
            raise ValueError("concept_id must be a short token without surrounding whitespace")
        return v
