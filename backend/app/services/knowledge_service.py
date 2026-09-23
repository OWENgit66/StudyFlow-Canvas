"""Coordinate stored chunks, fresh quality warnings, AI and atomic persistence."""
import hashlib
import json
from sqlalchemy import select,text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from pydantic import ValidationError

from app.models import Resource,DocumentChunk,ResourceKnowledge
from app.models.common import ResourceStatus
from app.schemas.knowledge import KnowledgeInput,KnowledgeResponse,ExtractionResult
from app.services.document_service import DocumentService
from app.services.document_errors import DocumentError
from app.services.material_paths import resolve_database_path
from app.services.ai_service import AIService
from app.services.ai_errors import KnowledgeInputError,KnowledgeNotFoundError,KnowledgeDatabaseError
from app.repositories.knowledge import save_knowledge, rebuild_summary


def source_state(db:Session, resource:Resource, documents:DocumentService):
    if not resource.local_path or resource.sync_status not in {ResourceStatus.parsed,ResourceStatus.completed}:
        raise KnowledgeInputError('Download and successfully parse this resource before generating knowledge.')
    path=resolve_database_path(resource.local_path)
    if not path.is_relative_to(documents.root) or not path.is_file():
        raise KnowledgeInputError('Original PDF is missing or outside the material directory.')
    try:
        with path.open('rb') as stream:
            digest=hashlib.file_digest(stream,'sha256').hexdigest()
    except OSError:
        raise KnowledgeInputError('Unable to read the original PDF.') from None
    chunks=db.scalars(select(DocumentChunk).where(DocumentChunk.resource_id==resource.id)
                      .order_by(DocumentChunk.chunk_index)).all()
    rows=[{'source_chunk_id':c.id,'resource_id':c.resource_id,'page_number':c.page_number,'chunk_index':c.chunk_index,'content':c.content} for c in chunks]
    encoded=json.dumps({'pipeline':'phase5.4-symbolic-fidelity','file':digest,'week':resource.week_id,
                        'canvas_updated_at':resource.canvas_updated_at.isoformat() if resource.canvas_updated_at else None,
                        'path':resource.local_path,'type':resource.file_type,'chunks':rows},sort_keys=True,ensure_ascii=False)
    return path,rows,hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def response_for(row:ResourceKnowledge, *, stale=False):
    return KnowledgeResponse(resource_id=row.resource_id,provider=row.provider,model=row.model,
                             source_fingerprint=row.source_fingerprint,stale=stale,
                             extraction=ExtractionResult.model_validate(row.payload))


class KnowledgeService:
    def __init__(self, documents:DocumentService):
        self.documents=documents

    def generate(self, db:Session, resource_id:int, ai:AIService):
        try:
            resource=db.get(Resource,resource_id)
            if resource is None:
                raise KnowledgeNotFoundError('Resource not found.')
            path,rows,fingerprint=source_state(db,resource,self.documents)
            try:
                document=self.documents.parse(path,resource.id,resource.file_type)
            except DocumentError:
                raise KnowledgeInputError('Unable to obtain current PDF quality warnings; parse the resource again.') from None
            current=[c.model_dump() for c in self.documents.chunk(document)]
            if document.possible_scanned_pdf or not rows or current!=[{k:v for k,v in row.items() if k!='source_chunk_id'} for row in rows]:
                raise KnowledgeInputError('Stored chunks do not match current parsing; parse the resource again.')
            warnings={p.page_number:[w.code for w in p.warnings] for p in document.pages}
            inputs=[KnowledgeInput(**row,warnings=warnings[row['page_number']]) for row in rows]
            # Release the read transaction before any slow or external call.
            db.rollback()
            result=ai.extract(inputs)
            if getattr(ai, 'on_stage', None):
                ai.on_stage('persistence')
            # SQLite write lock prevents another local writer changing sources during final check/save.
            db.execute(text('BEGIN IMMEDIATE'))
            db.expire_all()
            resource=db.get(Resource,resource_id)
            if resource is None or source_state(db,resource,self.documents)[2]!=fingerprint:
                raise KnowledgeInputError('Source changed during generation; retry with current chunks.')
            current_ids=self.current_ids(db, resource.week_id) | {resource.id}
            record=save_knowledge(db,resource,result,fingerprint,ai.provider.name,ai.provider.model,
                                  current_resource_ids=current_ids)
            resource.sync_status=ResourceStatus.completed
            response=response_for(record)
            db.commit()
            return response
        except SQLAlchemyError:
            db.rollback()
            raise KnowledgeDatabaseError('Knowledge save failed; database changes were rolled back.') from None
        except Exception:
            db.rollback()
            raise

    def current_ids(self, db, week_id):
        ids=set()
        for resource in db.scalars(select(Resource).where(Resource.week_id==week_id)).all():
            try:
                self.read(db, resource.id)
                ids.add(resource.id)
            except KnowledgeNotFoundError:
                pass
        return ids

    def refresh_summary(self, db, week_id):
        rebuild_summary(db, week_id, self.current_ids(db, week_id))

    def read(self,db:Session,resource_id:int, *, include_stale=False):
        try:
            resource=db.get(Resource,resource_id)
            row=db.get(ResourceKnowledge,resource_id)
            if resource is None or row is None:
                raise KnowledgeNotFoundError('Knowledge not generated for this resource.')
            try:
                stale=source_state(db,resource,self.documents)[2]!=row.source_fingerprint
            except KnowledgeInputError:
                stale=True
            if stale and not include_stale:
                raise KnowledgeNotFoundError('No current knowledge; historical output is stale.')
            return response_for(row,stale=stale)
        except (SQLAlchemyError,ValidationError):
            db.rollback()
            raise KnowledgeDatabaseError('Unable to read saved knowledge.') from None
