"""Internal support assessments, not fact-verification certificates."""
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SupportAssessment(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    supported: bool
    reason: str = Field(min_length=1, max_length=600)
    unsupported_parts: list[str] = Field(max_length=20)

    @model_validator(mode='after')
    def consistent_assessment(self):
        if self.supported and self.unsupported_parts:
            raise ValueError('Supported claims cannot contain unsupported parts.')
        if any(len(part) > 1000 for part in self.unsupported_parts):
            raise ValueError('Unsupported-part description is too long.')
        return self


class ClaimDecision(SupportAssessment):
    claim_id: str = Field(min_length=1, max_length=100)


class SemanticReview(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    decisions: list[ClaimDecision] = Field(max_length=24)


class SemanticSummary(BaseModel):
    accepted: int = 0  # Items retained unchanged.
    rejected: int = 0  # Entire items removed.
    partially_reduced: int = 0  # Retained items with unsupported fields removed.
    decisions: list[ClaimDecision] = Field(default_factory=list)
    batches: int = 0
    accepted_counts: dict[str, int] = Field(default_factory=dict)
    rejected_counts: dict[str, int] = Field(default_factory=dict)
    reduced_counts: dict[str, int] = Field(default_factory=dict)
