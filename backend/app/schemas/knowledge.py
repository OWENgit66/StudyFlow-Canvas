"""Strict provider output and source metadata. No provider-specific types."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.semantic import SupportAssessment, SemanticSummary

Text = Annotated[str, Field(max_length=6000)]
Pages = Annotated[list[Annotated[int, Field(gt=0)]], Field(min_length=1, max_length=100)]
ChunkIds = Annotated[list[Annotated[int, Field(gt=0)]], Field(min_length=1, max_length=100)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Evidence(StrictModel):
    page_number: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=1500)


class Sourced(StrictModel):
    source_chunk_ids: ChunkIds
    source_pages: Pages
    # Optional legacy/debug quotes are never used as evidence or persisted.
    evidence: list[Evidence] | None = None


class KnowledgeConcept(Sourced):
    name: str = Field(min_length=1, max_length=250)
    definition: Text
    explanation: Text
    importance: Literal['low', 'medium', 'high']


class KnowledgePoint(Sourced):
    content: Text


class KnowledgeExample(Sourced):
    description: Text


class KnowledgeQuestion(Sourced):
    question: Text
    answer: Text


class KnowledgeFormula(StrictModel):
    source_chunk_ids: ChunkIds
    formula: str = Field(min_length=1, max_length=1000)
    explanation: Text | None
    source_page: int = Field(gt=0)
    reliable: bool


class KnowledgeOutput(StrictModel):
    topic: Text
    overview: Text
    concepts: list[KnowledgeConcept] = Field(max_length=200)
    key_points: list[KnowledgePoint] = Field(max_length=200)
    formulas: list[KnowledgeFormula] = Field(max_length=200)
    examples: list[KnowledgeExample] = Field(max_length=200)
    exam_focus: list[KnowledgePoint] = Field(max_length=200)
    questions: list[KnowledgeQuestion] = Field(max_length=50)


class KnowledgeInput(StrictModel):
    source_chunk_id: int = Field(gt=0)
    resource_id: int
    page_number: int
    chunk_index: int
    content: str
    warnings: list[str]


class SourceEvidence(StrictModel):
    source_chunk_id: int
    page_number: int
    quote: str  # Actual complete stored chunk, not model-supplied text.
    warnings: list[str]


class SemanticMetadata(StrictModel):
    # Empty on pre-5.2 records: never imply old content was reviewed.
    semantic_support: dict[str, SupportAssessment] = Field(default_factory=dict)


class GroundedConcept(KnowledgeConcept, SemanticMetadata):
    evidence: list[SourceEvidence]
    source_warnings: list[str]


class GroundedPoint(KnowledgePoint, SemanticMetadata):
    evidence: list[SourceEvidence]
    source_warnings: list[str]


class GroundedExample(KnowledgeExample, SemanticMetadata):
    evidence: list[SourceEvidence]
    source_warnings: list[str]


class GroundedQuestion(KnowledgeQuestion, SemanticMetadata):
    evidence: list[SourceEvidence]
    source_warnings: list[str]


class GroundedFormula(KnowledgeFormula, SemanticMetadata):
    evidence: list[SourceEvidence]
    source_warnings: list[str]


class GroundedKnowledgeOutput(KnowledgeOutput):
    concepts: list[GroundedConcept] = Field(max_length=200)
    key_points: list[GroundedPoint] = Field(max_length=200)
    formulas: list[GroundedFormula] = Field(max_length=200)
    examples: list[GroundedExample] = Field(max_length=200)
    exam_focus: list[GroundedPoint] = Field(max_length=200)
    questions: list[GroundedQuestion] = Field(max_length=50)


def provider_output_schema() -> dict:
    """Only ask for provenance, never ask the provider to author evidence text.

    Optional debug quotes are accepted on input for diagnostics/legacy callers,
    but are absent from the provider contract. All advertised fields are required
    to preserve OpenAI's strict structured-output contract.
    """
    schema = KnowledgeOutput.model_json_schema()
    schema.get('$defs', {}).pop('Evidence', None)
    for definition in schema.get('$defs', {}).values():
        definition.get('properties', {}).pop('evidence', None)
    return schema


class ExtractionResult(BaseModel):
    knowledge: GroundedKnowledgeOutput
    batches: int
    formulas_omitted: int
    warnings: list[str]
    exam_focus_omitted: int = 0
    optional_items_omitted: dict[str, int] = Field(default_factory=dict)
    generated_counts: dict[str, int] = Field(default_factory=dict)
    formula_filtered_counts: dict[str, int] = Field(default_factory=dict)
    formula_reduced_counts: dict[str, int] = Field(default_factory=dict)
    input_masking: dict[str, int] = Field(default_factory=dict)
    semantic_review: SemanticSummary | None = None
    request_counts: dict[str, int] = Field(default_factory=dict)
    usage: list[dict] = Field(default_factory=list)


class KnowledgeResponse(BaseModel):
    resource_id: int
    provider: str
    model: str
    source_fingerprint: str
    stale: bool
    extraction: ExtractionResult
