"""Course Q&A over the shared live index; generation never creates embeddings."""
from functools import lru_cache
from threading import Lock

from app.core.config import Settings
from app.models import DocumentChunk, Resource, Week
from app.services.ai_errors import AIConfigurationError, AITransientError
from app.services.llm_factory import create_llm_provider
from app.services.retrieval_service import fingerprints, usable
from app.services.course_index import CourseIndexService, local_embedding

_inference_lock = Lock()


@lru_cache(maxsize=1)
def _runtime():
    from app.services.rag_answer_service import RAGAnswerService
    from app.services.retrieval_service import RetrievalService
    from app.services.reranker_provider import LocalRerankerProvider
    try:
        return RAGAnswerService(RetrievalService(local_embedding()), LocalRerankerProvider(allow_download=False))
    except Exception:
        raise AIConfigurationError('Course Q&A local models are unavailable. Check the local model cache.') from None


def validate_current_sources(db, evidence, course_id, captured=None):
    hashes = {}
    for item in evidence:
        chunk = db.get(DocumentChunk, item.chunk_id)
        resource = db.get(Resource, item.resource_id)
        week = db.get(Week, item.week_id)
        if (not chunk or not resource or not week
                or chunk.resource_id != resource.id or resource.week_id != week.id
                or week.course_id != course_id or item.course_id != course_id or not usable(chunk, resource)
                or chunk.page_number != item.page or chunk.content != item.text
                or resource.filename != item.title or week.title != item.week
                or resource.resource_type.value != item.resource_type
                or (captured is not None and fingerprints(chunk, resource) != captured.get(chunk.id))):
            raise AIConfigurationError('Course Q&A index is stale. Source material needs an updated index.')
        hashes[chunk.id] = fingerprints(chunk, resource)
    return hashes


def require_ready(db, course_id, service):
    status = CourseIndexService(service.retrieval.provider).status(db, course_id)
    if status['state'] != 'ready':
        raise AIConfigurationError(status['message'])


class CourseQAService:
    def ask(self, db, course_id, question, *, week_id=None, resource_type=None):
        # Single-user prototype: avoid parallel local inference and duplicate paid requests.
        if not _inference_lock.acquire(blocking=False):
            raise AITransientError('Course Q&A is busy. Wait for the current answer.')
        try:
            service = _runtime()
            require_ready(db, course_id, service)
            evidence = service.prepare(db, course_id, question,
                                       week_id=week_id, resource_type=resource_type)
            db.rollback(); db.expire_all()
            require_ready(db, course_id, service)
            captured = validate_current_sources(db, evidence, course_id)
            db.rollback()  # Do not hold a live database transaction over the provider call.
            from app.services.rag_answer_service import RAGAnswerService
            answer_service = RAGAnswerService(service.retrieval, service.reranker,
                create_llm_provider(Settings()) if evidence else None)
            result = answer_service.generate(question, evidence)
            db.expire_all()
            require_ready(db, course_id, service)
            validate_current_sources(db, evidence, course_id, captured)
            return result
        finally:
            _inference_lock.release()
