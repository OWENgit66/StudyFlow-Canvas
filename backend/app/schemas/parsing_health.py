"""Student-facing parsing review; excludes extraction/debug metadata."""
from typing import Literal
from pydantic import BaseModel, Field


class ParsingIssue(BaseModel):
    page_number: int = Field(ge=1)
    category: str
    label: str
    explanation: str
    severity: Literal['info', 'warning', 'critical']
    occurrences: int = Field(ge=1, default=1)


class ParsingHealth(BaseModel):
    status: Literal['healthy', 'review', 'unable_to_parse', 'unknown', 'stale', 'unavailable', 'unsupported']
    total_pages: int | None = None
    pages_with_text: int | None = None
    pages_need_review: int = 0
    pages_with_encoding_warnings: int = 0
    possible_scanned_pdf: bool | None = None
    issues: list[ParsingIssue] = Field(default_factory=list)
