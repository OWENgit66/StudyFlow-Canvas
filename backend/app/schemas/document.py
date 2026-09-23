"""Page-level extraction and compact processing results."""

from typing import Literal

from pydantic import BaseModel, Field, computed_field


class TextSpan(BaseModel):
    text: str
    bbox: tuple[float, float, float, float]
    origin: tuple[float, float]
    font: str
    size: float
    flags: int
    line_index: int
    direction: tuple[float, float] = (1, 0)


class ParsingWarning(BaseModel):
    code: Literal["suspicious_formula_layout", "unusual_symbol_position", "empty_text",
                  "possible_scanned_page", "repeated_header_footer", "encoding_warning"]
    message: str
    occurrences: int = Field(default=1, ge=1)
    span_indices: list[int] = Field(default_factory=list)


class PageQuality(BaseModel):
    page_number: int
    warnings: list[ParsingWarning]


class ParsedPage(BaseModel):
    page_number: int = Field(ge=1)
    text: str  # Backward-compatible cleaned text used for chunking.
    raw_text: str = ""
    width: float = 0
    height: float = 0
    spans: list[TextSpan] = Field(default_factory=list)
    warnings: list[ParsingWarning] = Field(default_factory=list)
    repeated_headers_removed: int = 0
    repeated_footers_removed: int = 0

    @computed_field
    @property
    def cleaned_text(self) -> str:
        return self.text

    @computed_field
    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())

    @computed_field
    @property
    def character_count(self) -> int:
        return len(self.text)


class ParsedDocument(BaseModel):
    resource_id: int
    filename: str
    pages: list[ParsedPage]
    metadata: dict[str, str] = Field(default_factory=dict)
    possible_scanned_pdf: bool = False
    warnings: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def total_pages(self) -> int:
        return len(self.pages)

    @computed_field
    @property
    def pages_with_text(self) -> int:
        return sum(page.has_text for page in self.pages)

    @computed_field
    @property
    def empty_pages(self) -> int:
        return self.total_pages - self.pages_with_text

    @computed_field
    @property
    def total_characters(self) -> int:
        return sum(page.character_count for page in self.pages)


    @computed_field
    @property
    def page_warnings(self) -> list[PageQuality]:
        return [PageQuality(page_number=p.page_number, warnings=p.warnings) for p in self.pages if p.warnings]

    @computed_field
    @property
    def pages_with_warnings(self) -> int:
        return sum(bool(p.warnings) for p in self.pages)

    @computed_field
    @property
    def pages_with_formula_warnings(self) -> int:
        return sum(any(w.code == "suspicious_formula_layout" for w in p.warnings) for p in self.pages)

    @computed_field
    @property
    def pages_with_encoding_warnings(self) -> int:
        return sum(any(w.code == "encoding_warning" for w in p.warnings) for p in self.pages)

    @computed_field
    @property
    def repeated_headers_removed(self) -> int:
        return sum(p.repeated_headers_removed for p in self.pages)

    @computed_field
    @property
    def repeated_footers_removed(self) -> int:
        return sum(p.repeated_footers_removed for p in self.pages)


class ParseSummary(BaseModel):
    resource_id: int
    filename: str
    total_pages: int
    pages_with_text: int
    empty_pages: int
    total_characters: int
    chunks_created: int
    possible_scanned_pdf: bool
    status: Literal["parsed", "needs_ocr"]
    warnings: list[str] = Field(default_factory=list)

    pages_with_warnings: int = 0
    pages_with_formula_warnings: int = 0
    pages_with_encoding_warnings: int = 0
    repeated_headers_removed: int = 0
    repeated_footers_removed: int = 0
    page_warnings: list[PageQuality] = Field(default_factory=list)
