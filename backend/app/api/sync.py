from typing import Annotated
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.core.config import Settings
from app.core.database import get_db
from app.models import SyncRecord
from app.schemas.sync import SyncRequest
from app.schemas.sync_record import SyncRecordRead
from app.services.sync_service import SyncService, SyncBusyError, request_cancellation, cancellation_requested
from app.services.canvas_service import CanvasService
from app.services.document_service import DocumentService
from app.services.knowledge_service import KnowledgeService
from app.services.ai_service import AIService
from app.services.llm_factory import create_llm_provider

router = APIRouter(prefix='/api', tags=['sync'])
DB = Annotated[Session, Depends(get_db)]


def get_sync_service():
    settings = Settings()
    documents = DocumentService(settings)
    return SyncService(settings, lambda: CanvasService(settings), documents,
                       KnowledgeService(documents), lambda: AIService(create_llm_provider(settings), settings))


@router.post('/sync', response_model=SyncRecordRead)
def sync(db: DB, service: Annotated[SyncService, Depends(get_sync_service)],
         tasks: BackgroundTasks, http_request: Request, response: Response,
         request: SyncRequest | None = None, dry_run: bool = False, background: bool = False):
    try:
        if background:
            scope = request or SyncRequest()
            record = service.reserve(db, scope, dry_run=dry_run)
            result = SyncRecordRead.model_validate(record)
            factory = http_request.app.state.session_factory

            def execute():
                with factory() as session:
                    service.run(session, scope, dry_run=dry_run, reserved_id=record.id)

            tasks.add_task(execute)
            response.status_code = 202
            return result
        return service.run(db, request or SyncRequest(), dry_run=dry_run)
    except SyncBusyError:
        raise HTTPException(409, 'A sync is already running.') from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(500, 'Unable to persist sync progress; database operation failed.') from None


@router.get('/sync/current', response_model=SyncRecordRead | None)
def current(db: DB):
    record = db.scalar(select(SyncRecord).where(SyncRecord.status == 'running').order_by(SyncRecord.id.desc()))
    return present(record) if record else None


def present(record):
    result = SyncRecordRead.model_validate(record)
    if cancellation_requested(record.id):
        result.details = {**result.details, 'cancel_requested': True}
    return result


@router.post('/sync/{sync_id}/cancel', response_model=SyncRecordRead)
def cancel(sync_id: Annotated[int, Path(gt=0)], db: DB):
    record = db.get(SyncRecord, sync_id)
    if record is None:
        raise HTTPException(404, 'Sync record not found.')
    if record.status != 'running':
        return record
    if not request_cancellation(sync_id):
        raise HTTPException(409, 'This sync is not active in this backend process.')
    # The worker alone writes telemetry. A second session must not overwrite a
    # newer progress snapshot with the stale JSON it read before cancellation.
    return present(record)


@router.get('/sync/{sync_id}', response_model=SyncRecordRead)
def read(sync_id: Annotated[int, Path(gt=0)], db: DB):
    record = db.get(SyncRecord, sync_id)
    if record is None:
        raise HTTPException(404, 'Sync record not found.')
    return present(record)
