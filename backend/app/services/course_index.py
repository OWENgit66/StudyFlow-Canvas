"""Shared SQLite course indexes. Reuse prototype hashing, encoding and retrieval."""
from functools import lru_cache
from threading import Lock

from sqlalchemy import delete, select, update, or_

from app.models import ChunkEmbedding, Course, DocumentChunk
from app.models.common import utc_now
from app.services.embedding_provider import LocalEmbeddingProvider, unit_vector
from app.services.retrieval_service import RetrievalService, course_chunks, current_embedding, usable

MULTILINGUAL_MODEL = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
_index_lock = Lock()  # Local single-worker application; CLI must not run alongside a sync index job.


@lru_cache(maxsize=1)
def local_embedding():
    return LocalEmbeddingProvider(model=MULTILINGUAL_MODEL, allow_download=False)


def save_report(db, course_id, report):
    db.execute(update(Course).where(Course.id == course_id).values(
        indexing_report=report, updated_at=Course.updated_at))
    db.commit()


def recover_interrupted_indexes(db):
    for course in db.scalars(select(Course)):
        if (course.indexing_report or {}).get('state') == 'indexing':
            save_report(db, course.id, {'state': 'error', 'message': 'Indexing was interrupted. Sync this course again.'})


class CourseIndexService:
    def __init__(self, provider):
        self.provider = provider
        self.retrieval = RetrievalService(provider)

    def status(self, db, course_id, *, ignore_report=False):
        rows = course_chunks(db, course_id)
        course = db.get(Course, course_id)
        report = course.indexing_report or {}
        total = compatible = 0
        for chunk, resource, _, _ in rows:
            if not usable(chunk, resource):
                continue
            total += 1
            row = db.get(ChunkEmbedding, chunk.id)
            if current_embedding(row, chunk, resource, self.provider):
                try:
                    unit_vector(row.embedding, self.provider.dimensions)
                    compatible += 1
                except ValueError:
                    pass
        state = ('unavailable' if not total else 'ready' if total == compatible else 'stale')
        if not ignore_report and report.get('state') in {'indexing', 'error'}:
            state = report['state']
        messages = {'ready': 'Course Q&A is ready.', 'stale': 'Course Q&A is not ready yet. Sync this course to update its index.',
                    'unavailable': 'No parsed course text is available yet.', 'indexing': 'Indexing course materials…',
                    'error': 'Course indexing failed or was interrupted. Sync this course to retry.'}
        return {'state': state, 'message': messages[state], 'total_chunks': total,
                'indexed_chunks': compatible, 'missing_chunks': total - compatible}

    def index_course(self, db, course_id):
        if db.get(Course, course_id) is None:
            raise ValueError('Course not found.')
        if not _index_lock.acquire(blocking=False):
            raise ValueError('Another course index is running; retry later.')
        try:
            state = Course.indexing_report['state'].as_string()
            claimed = db.execute(update(Course).where(Course.id == course_id,
                or_(state.is_(None), state != 'indexing')).values(
                indexing_report={'state': 'indexing', 'started_at': utc_now().isoformat()},
                updated_at=Course.updated_at)).rowcount
            db.commit()
            if not claimed:
                raise ValueError('This course is already being indexed.')
            try:
                rows = course_chunks(db, course_id)
                valid = [chunk.id for chunk, resource, _, _ in rows if usable(chunk, resource)]
                invalid = [chunk.id for chunk, resource, _, _ in rows if not usable(chunk, resource)]
                existing = set(db.scalars(select(ChunkEmbedding.chunk_id).where(ChunkEmbedding.chunk_id.in_(valid))))
                # FK CASCADE already removes normal deleted chunks. Also repair orphan
                # indexes from legacy connections that had foreign_keys disabled.
                removed = db.execute(delete(ChunkEmbedding).where(
                    ~ChunkEmbedding.chunk_id.in_(select(DocumentChunk.id)))).rowcount
                if invalid:
                    removed += db.execute(delete(ChunkEmbedding).where(ChunkEmbedding.chunk_id.in_(invalid))).rowcount
                db.commit()
                stats = self.retrieval.index_course(db, course_id)
                readiness = self.status(db, course_id, ignore_report=True)
                if readiness['missing_chunks']:
                    raise ValueError('Course changed during indexing; rerun.')
                new = len(set(valid) - existing)
                result = {'total_chunks': len(valid), 'new_embeddings': new,
                          'updated_embeddings': stats['generated'] - new,
                          'skipped_embeddings': stats['skipped'], 'removed_stale': removed,
                          'unusable_chunks': stats['unusable']}
                save_report(db, course_id, {'state': readiness['state'], 'model': self.provider.model,
                    'model_version': self.provider.model_version, 'completed_at': utc_now().isoformat(), 'stats': result})
                return result
            except Exception:
                db.rollback()
                save_report(db, course_id, {'state': 'error', 'message': 'Local indexing failed. Completed material sync is preserved.'})
                raise
        finally:
            _index_lock.release()


def index_course(db, course_id):
    """Production entrypoint, including model initialization failures. No remote calls."""
    try:
        return CourseIndexService(local_embedding()).index_course(db, course_id)
    except Exception:
        db.rollback()
        # Do not overwrite another active index worker's progress.
        course = db.get(Course, course_id)
        if course and (course.indexing_report or {}).get('state') != 'indexing':
            save_report(db, course_id, {'state': 'error', 'message': 'Local indexing failed. Check the local model cache and retry sync.'})
        raise


def index_status(db, course_id):
    course = db.get(Course, course_id)
    if course is None:
        raise ValueError('Course not found.')
    report = course.indexing_report or {}
    if report.get('state') == 'indexing':
        return {'state': 'indexing', 'message': 'Indexing course materials…',
                'total_chunks': 0, 'indexed_chunks': 0, 'missing_chunks': 0}
    try:
        return CourseIndexService(local_embedding()).status(db, course_id)
    except Exception:
        return {'state': 'unavailable', 'message': 'Local embedding model is unavailable. Check the local model cache.',
                'total_chunks': 0, 'indexed_chunks': 0, 'missing_chunks': 0}
