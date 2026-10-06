"""Course-scoped local indexing and cosine retrieval over existing source chunks."""
import hashlib
import json
from dataclasses import dataclass, asdict

from sqlalchemy import func, select, text

from app.models import ChunkEmbedding, Course, DocumentChunk, Resource, Week
from app.models.common import ResourceType, utc_now
from app.services.embedding_provider import EmbeddingProvider, unit_vector
from app.services.retrieval_hygiene import low_information_reason


def cosine_similarity(left, right):
    a, b = unit_vector(left), unit_vector(right, len(left))
    return max(-1.0, min(1.0, sum(x*y for x, y in zip(a, b))))


def course_stats(db, course_id):
    course = db.get(Course, course_id)
    if course is None:
        raise ValueError('Course not found.')
    resources = db.scalar(select(func.count(Resource.id)).join(Week).where(Week.course_id == course_id))
    chunks = db.scalar(select(func.count(DocumentChunk.id)).join(Resource).join(Week)
                       .where(Week.course_id == course_id))
    return {'course_id': course.id, 'course_code': course.code, 'course_name': course.name,
            'resources': resources, 'chunks': chunks}


def course_chunks(db, course_id, resource_types=None):
    course_stats(db, course_id)  # Missing course is not silently treated as an empty corpus.
    statement = (select(DocumentChunk, Resource, Week, Course).select_from(DocumentChunk)
                 .join(Resource, DocumentChunk.resource_id == Resource.id)
                 .join(Week, Resource.week_id == Week.id).join(Course, Week.course_id == Course.id)
                 .where(Course.id == course_id).order_by(DocumentChunk.id))
    if resource_types is not None:
        types = [ResourceType(role) for role in resource_types]
        statement = statement.where(Resource.resource_type.in_(types))
    return db.execute(statement).all()


def fingerprints(chunk, resource):
    content_hash = hashlib.sha256(chunk.content.encode('utf-8')).hexdigest()
    identity = [chunk.resource_id, chunk.page_number, chunk.chunk_index, resource.week_id,
                str(resource.canvas_updated_at), resource.external_revision, resource.local_path,
                resource.parsing_report]
    source_hash = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return content_hash, source_hash


def usable(chunk, resource):
    # A failed knowledge call does not invalidate parsed text. A pending/replaced
    # download or failed parse may still retain OLD chunks and must be excluded.
    return bool(chunk.content.strip()) and (
        resource.sync_status in {'parsed', 'completed'} or
        (resource.sync_status == 'failed' and resource.sync_stage == 'knowledge'))


def current_embedding(row, chunk, resource, provider):
    return (row is not None and row.model == provider.model
            and row.model_version == provider.model_version and row.dimensions == provider.dimensions
            and (row.content_hash, row.source_hash) == fingerprints(chunk, resource))


@dataclass
class RetrievalHit:
    chunk_id: int
    score: float
    text: str
    resource_id: int
    resource_title: str
    course_id: int
    course_code: str
    course_name: str
    week_id: int
    week_title: str
    page_number: int
    resource_type: str
    source_link: str | None
    parsing_warnings: list[str]
    parsing_health: str

    def to_dict(self):
        return asdict(self)


class RetrievalService:
    def __init__(self, provider: EmbeddingProvider):
        self.provider = provider

    def index_course(self, db, course_id, *, batch_size=16):
        if not 1 <= batch_size <= 128:
            raise ValueError('Batch size must be between 1 and 128.')
        rows = course_chunks(db, course_id)
        stats = {'total_chunks': len(rows), 'generated': 0, 'skipped': 0, 'unusable': 0}
        pending = []
        for chunk, resource, _, _ in rows:
            if not usable(chunk, resource):
                stats['unusable'] += 1
                continue
            existing = db.get(ChunkEmbedding, chunk.id)
            if current_embedding(existing, chunk, resource, self.provider):
                try:
                    unit_vector(existing.embedding, self.provider.dimensions)
                    stats['skipped'] += 1
                    continue
                except ValueError:
                    pass
            pending.append((chunk.id, chunk.content, fingerprints(chunk, resource)))
        db.rollback()  # No DB transaction held over inference.
        for start in range(0, len(pending), batch_size):
            batch = pending[start:start+batch_size]
            vectors = self.provider.embed([item[1] for item in batch])
            if len(vectors) != len(batch):
                raise ValueError('Embedding count does not match input count.')
            vectors = [unit_vector(v, self.provider.dimensions) for v in vectors]
            try:
                db.execute(text('BEGIN IMMEDIATE'))
                db.expire_all()
                for (chunk_id, _, hashes), vector in zip(batch, vectors):
                    chunk = db.get(DocumentChunk, chunk_id)
                    resource = db.get(Resource, chunk.resource_id) if chunk else None
                    week = db.get(Week, resource.week_id) if resource else None
                    if (not week or week.course_id != course_id or not usable(chunk, resource)
                            or fingerprints(chunk, resource) != hashes):
                        raise ValueError('Source changed during embedding; rerun indexing.')
                    row = db.get(ChunkEmbedding, chunk_id)
                    if row is None:
                        row = ChunkEmbedding(chunk_id=chunk_id)
                        db.add(row)
                    row.model, row.model_version = self.provider.model, self.provider.model_version
                    row.content_hash, row.source_hash = hashes
                    row.dimensions, row.embedding = self.provider.dimensions, vector
                    row.generated_at = utc_now()
                db.commit()
                stats['generated'] += len(batch)
            except Exception:
                db.rollback()
                raise
        return stats

    def search(self, db, course_id, query, *, top_k=5, resource_types=None, diagnostics=None):
        if not query.strip() or len(query) > 4000 or not 1 <= top_k <= 100:
            raise ValueError('Require a nonempty query (max 4000 characters) and top_k 1..100.')
        candidates = {}
        for chunk, resource, week, course in course_chunks(db, course_id, resource_types):
            embedding = db.get(ChunkEmbedding, chunk.id)
            if usable(chunk, resource) and current_embedding(embedding, chunk, resource, self.provider):
                try:
                    vector = unit_vector(embedding.embedding, self.provider.dimensions)
                except ValueError:
                    continue
                reason = low_information_reason(chunk.content)
                if reason:
                    if diagnostics is not None:
                        diagnostics.append({'chunk_id': chunk.id, 'resource_id': resource.id,
                                            'page_number': chunk.page_number,
                                            'low_information_reason': reason})
                    continue
                candidates[chunk.id] = (vector, fingerprints(chunk, resource))
        if not candidates:
            return []  # No implicit indexing or provider call when there is no index.
        db.rollback()
        query_vector = unit_vector(self.provider.embed_query(query), self.provider.dimensions)
        db.expire_all()
        results = []
        # Query inference must not permit stale text, moved resources or changed
        # role filters to leak through a previously captured candidate list.
        for chunk, resource, week, course in course_chunks(db, course_id, resource_types):
            captured = candidates.get(chunk.id)
            if not captured or not usable(chunk, resource) or captured[1] != fingerprints(chunk, resource):
                continue
            vector = captured[0]
            report = (resource.parsing_report or {}).get('health', {})
            warnings = sorted({issue['category'] for issue in report.get('issues', [])
                               if issue.get('page_number') == chunk.page_number and 'category' in issue})
            results.append(RetrievalHit(chunk_id=chunk.id,
                score=cosine_similarity(query_vector, vector), text=chunk.content,
                resource_id=resource.id, resource_title=resource.filename,
                course_id=course.id, course_code=course.code, course_name=course.name,
                week_id=week.id, week_title=week.title, page_number=chunk.page_number,
                resource_type=resource.resource_type.value,
                source_link=f'/api/resources/{resource.id}/file#page={chunk.page_number}' if resource.local_path else None,
                parsing_warnings=warnings, parsing_health=report.get('status', 'unknown')))
        return sorted(results, key=lambda result: (-result.score, result.chunk_id))[:top_k]
