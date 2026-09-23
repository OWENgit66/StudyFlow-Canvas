"""Process one resource. Owns the request session's commit/rollback boundary."""

import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Resource
from app.models.common import ResourceStatus
from app.repositories.document_chunks import replace_chunks
from app.schemas.document import ParseSummary
from app.services.document_errors import (
    DocumentError, InvalidDocumentError, ResourceNotFoundError, DocumentDatabaseError,
)
from app.services.document_service import DocumentService
from app.services.material_paths import resolve_database_path
from app.services.parsing_health import source_fingerprint, build_report, store_report
from app.schemas.parsing_health import ParsingHealth

logger = logging.getLogger(__name__)


def process_resource(db: Session, resource_id: int, documents: DocumentService) -> ParseSummary:
    try:
        resource = db.get(Resource, resource_id)
        if resource is None:
            raise ResourceNotFoundError("Resource not found.")
        fingerprint = source_fingerprint(resource, documents.root)
        try:
            if not resource.local_path:
                raise InvalidDocumentError("Resource has no local file; download it before parsing.")
            document = documents.parse(resolve_database_path(resource.local_path), resource.id, resource.file_type)
            chunks = [] if document.possible_scanned_pdf else documents.chunk(document)
            if fingerprint != source_fingerprint(resource, documents.root):
                raise InvalidDocumentError('Source changed while parsing; retry with the current file.')
        except DocumentError as error:
            # Parsing happens before deleting any chunks. Preserve old chunks on failure.
            resource.sync_status = ResourceStatus.failed
            store_report(resource, fingerprint, ParsingHealth(status='unable_to_parse'))
            db.commit()
            logger.warning("Failed to parse resource %d: %s", resource_id, error.code)
            raise

        if document.possible_scanned_pdf:
            resource.sync_status = ResourceStatus.failed
            status = "needs_ocr"
        else:
            replace_chunks(db, resource_id, chunks)
            resource.sync_status = ResourceStatus.parsed
            status = "parsed"
        store_report(resource, fingerprint, build_report(document))
        result = ParseSummary(
            **document.model_dump(exclude={"pages", "metadata"}),
            chunks_created=len(chunks), status=status,
        )
        db.commit()
        logger.info("Resource %d: saved %d chunks; status %s", resource_id, len(chunks), status)
        return result
    except SQLAlchemyError:
        db.rollback()
        logger.error("Document database operation failed for resource %d", resource_id)
        raise DocumentDatabaseError("Unable to save document chunks; database changes were rolled back.") from None
