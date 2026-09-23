from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import get_db
from app.models import Resource
from app.repositories.document_chunks import list_chunks
from app.schemas.document import ParseSummary
from app.schemas.document_chunk import DocumentChunkRead
from app.services.document_errors import DocumentError, DocumentDatabaseError, ResourceNotFoundError
from app.services.document_processing import process_resource
from app.services.document_service import DocumentService

router = APIRouter(prefix="/api/resources", tags=["documents"])
DB = Annotated[Session, Depends(get_db)]
ID = Annotated[int, Path(gt=0)]


def get_document_service() -> DocumentService:
    return DocumentService(Settings())


async def document_error_handler(_request: Request, error: DocumentError) -> JSONResponse:
    return JSONResponse(status_code=error.http_status, content={
        "detail": {"code": error.code, "message": str(error)},
    })


@router.post("/{resource_id}/parse", response_model=ParseSummary)
def parse_resource(resource_id: ID, db: DB, documents: Annotated[DocumentService, Depends(get_document_service)]):
    return process_resource(db, resource_id, documents)


@router.get("/{resource_id}/chunks", response_model=list[DocumentChunkRead])
def get_chunks(resource_id: ID, db: DB,
               offset: Annotated[int, Query(ge=0)] = 0,
               limit: Annotated[int, Query(ge=1, le=200)] = 100):
    try:
        if db.get(Resource, resource_id) is None:
            raise ResourceNotFoundError("Resource not found.")
        return list_chunks(db, resource_id, offset, limit)
    except SQLAlchemyError:
        db.rollback()
        raise DocumentDatabaseError("Unable to read document chunks.") from None
