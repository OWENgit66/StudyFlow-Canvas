"""Local PDF validation, page extraction and chunking. No network or database IO."""

import logging
from pathlib import Path
from threading import Lock

import pymupdf

from app.core.config import Settings
from app.schemas.document import ParsedDocument
from app.schemas.document_chunk import DocumentChunkCreate
from app.services.document_chunking import split_page
from app.services.document_quality import extract_page, remove_repeated_margins
from app.services.document_errors import InvalidDocumentError, DocumentParseError, DocumentError
from app.services.material_paths import material_root

logger = logging.getLogger(__name__)
_pdf_lock = Lock()  # PyMuPDF calls are serialized within this MVP backend process.


class DocumentService:
    def __init__(self, settings: Settings):
        self.root = material_root(settings)
        self.chunk_size = settings.document_chunk_size
        self.chunk_overlap = settings.document_chunk_overlap

    def parse(self, path: Path, resource_id: int, file_type: str = "pdf") -> ParsedDocument:
        try:
            path = path.resolve()
            if not path.is_relative_to(self.root):
                raise InvalidDocumentError("Resource path is outside MATERIALS_ROOT.")
            if path.suffix.lower() != ".pdf" or file_type.lower() not in {"pdf", ".pdf", "application/pdf"}:
                raise InvalidDocumentError("Unsupported document type; Phase 4 supports PDF only.")
            if not path.is_file():
                raise InvalidDocumentError("Local PDF file does not exist.")
            if path.stat().st_size == 0:
                raise InvalidDocumentError("Local PDF is empty.")
            with path.open("rb") as stream:
                if b"%PDF-" not in stream.read(1024):
                    raise InvalidDocumentError("File is not a valid PDF.")
            logger.info("Parsing resource %d", resource_id)
            with _pdf_lock, pymupdf.open(path) as pdf:
                if not pdf.is_pdf or pdf.page_count == 0:
                    raise InvalidDocumentError("File is not a readable PDF.")
                if pdf.needs_pass:
                    raise InvalidDocumentError("Password-protected PDF is not supported.")
                pages = [extract_page(page, index + 1) for index, page in enumerate(pdf)]
                remove_repeated_margins(pages)
                metadata = {key: value for key, value in (pdf.metadata or {}).items() if isinstance(value, str)}
                document = ParsedDocument(resource_id=resource_id, filename=path.name, pages=pages, metadata=metadata)
                if pdf.is_repaired:
                    document.warnings.append("PDF structure was repaired by PyMuPDF; review extraction quality.")
            # Conservative empty-page heuristic, not an OCR/scanner classifier.
            document.possible_scanned_pdf = document.pages_with_text / document.total_pages <= 0.1
            if document.possible_scanned_pdf:
                document.warnings.append("PDF contains little or no extractable text. OCR may be required in a future phase.")
            elif document.empty_pages:
                document.warnings.append("Some pages contain no extractable text; images and diagrams were not interpreted.")
            logger.info("Resource %d: %d pages, %d with text", resource_id, document.total_pages, document.pages_with_text)
            return document
        except DocumentError:
            raise
        except (OSError, RuntimeError, ValueError) as error:
            logger.warning("PDF parsing failed for resource %d (%s)", resource_id, type(error).__name__)
            raise DocumentParseError("Unable to open or extract PDF; the file may be damaged or unreadable.") from None

    def chunk(self, document: ParsedDocument) -> list[DocumentChunkCreate]:
        chunks = []
        for page in document.pages:
            for content in split_page(page.text, self.chunk_size, self.chunk_overlap):
                chunks.append(DocumentChunkCreate(
                    resource_id=document.resource_id, page_number=page.page_number,
                    chunk_index=len(chunks), content=content,
                ))
        return chunks
