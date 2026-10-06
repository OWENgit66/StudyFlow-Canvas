import json
import math
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import delete, func, select

from app.models import ChunkEmbedding, Course, DocumentChunk, Resource, Week
from app.models.common import ResourceStatus, ResourceType
from app.repositories.document_chunks import replace_chunks
from app.schemas.document_chunk import DocumentChunkCreate
from app.services.embedding_provider import unit_vector, LocalEmbeddingProvider
from app.services.retrieval_service import RetrievalService, cosine_similarity, course_stats
from evals import rag_retrieval


class FakeEmbedding:
    model = 'synthetic'
    model_version = '1'
    dimensions = 2

    def __init__(self):
        self.inputs = []
        self.queries = []

    def embed(self, texts):
        self.inputs.extend(texts)
        return [{'first': [1., 0.], 'second': [.8, .6], 'third': [0., 1.],
                 'foreign': [1., 0.], 'changed': [-1., 0.]}[t] for t in texts]

    def embed_query(self, text):
        self.queries.append(text)
        return [1., 0.]


@pytest.fixture
def corpus(db, graph):
    semester, course, week, resource = graph
    resource.filename = 'Lecture.pdf'
    resource.sync_status = ResourceStatus.parsed
    resource.resource_type = ResourceType.lecture
    resource.local_path = 'materials/synthetic.pdf'
    resource.parsing_report = {'health': {'status': 'review', 'issues': [
        {'page_number': 2, 'category': 'suspicious_formula_layout'}]}}
    tutorial = Resource(week_id=week.id, filename='Tutorial.pdf', file_type='pdf',
                        sync_status=ResourceStatus.parsed, resource_type=ResourceType.tutorial)
    other = Resource(week_id=week.id, filename='Notes.pdf', file_type='pdf', sync_status=ResourceStatus.parsed)
    foreign_course = Course(semester_id=semester.id, name='Another course', code='OTHER')
    foreign_week = Week(course=foreign_course, week_number=1, title='Foreign')
    foreign = Resource(week=foreign_week, filename='Foreign.pdf', file_type='pdf', sync_status=ResourceStatus.parsed)
    db.add_all([tutorial, other, foreign])
    db.flush()
    chunks = [DocumentChunk(resource=r, page_number=2, chunk_index=0, content=t)
              for r, t in zip([resource, tutorial, other, foreign], ['first', 'second', 'third', 'foreign'])]
    db.add_all(chunks)
    db.commit()
    return course.id, foreign_course.id, chunks


@pytest.mark.parametrize('left,right,expected', [([1, 0], [1, 0], 1), ([1, 0], [0, 1], 0),
    ([1, 0], [-1, 0], -1), ([10, 0], [3, 4], .6), ([1e300, 0], [1e300, 0], 1)])
def test_cosine(left, right, expected):
    assert cosine_similarity(left, right) == pytest.approx(expected)


@pytest.mark.parametrize('values', [[], [0, 0], [math.nan, 0], [math.inf, 0], ['1', 2], [True, 0]])
def test_invalid_vectors(values):
    with pytest.raises(ValueError):
        unit_vector(values)


def test_course_scope_ranking_and_complete_metadata(db, corpus):
    course, foreign_course, chunks = corpus
    provider = FakeEmbedding()
    service = RetrievalService(provider)
    assert course_stats(db, course)['resources'] == 3
    assert service.index_course(db, course)['generated'] == 3
    assert 'foreign' not in provider.inputs
    service.index_course(db, foreign_course)
    found = service.search(db, course, 'query', top_k=2)
    assert [hit.chunk_id for hit in found] == [chunks[0].id, chunks[1].id]
    assert [hit.score for hit in found] == pytest.approx([1, .8])
    assert all(hit.course_id == course for hit in found)
    hit = found[0]
    assert hit.text == 'first' and hit.resource_title == 'Lecture.pdf'
    assert hit.resource_id == chunks[0].resource_id and hit.page_number == 2
    assert hit.week_title == 'Link Layer' and hit.course_code == 'COMPXXXX'
    assert hit.resource_type == 'lecture'
    assert hit.source_link == f'/api/resources/{hit.resource_id}/file#page=2'
    assert hit.parsing_warnings == ['suspicious_formula_layout']
    assert hit.to_dict()['parsing_health'] == 'review'


def test_default_includes_other_and_optional_filter(db, corpus):
    course, _, chunks = corpus
    service = RetrievalService(FakeEmbedding())
    service.index_course(db, course)
    assert len(service.search(db, course, 'q')) == 3
    assert [h.chunk_id for h in service.search(db, course, 'q', resource_types=['other'])] == [chunks[2].id]
    assert len(service.search(db, course, 'q', resource_types=['lecture', 'tutorial'])) == 2
    assert service.search(db, course, 'q', resource_types=[]) == []
    with pytest.raises(ValueError):
        service.search(db, course, 'q', resource_types=['invalid'])


def test_missing_index_does_not_generate_or_query(db, corpus):
    provider = FakeEmbedding()
    service = RetrievalService(provider)
    assert service.search(db, corpus[0], 'q') == []
    assert provider.inputs == provider.queries == []
    service.index_course(db, corpus[0])
    db.execute(delete(ChunkEmbedding).where(ChunkEmbedding.chunk_id == corpus[2][0].id))
    db.commit()
    assert len(service.search(db, corpus[0], 'q')) == 2


def test_content_change_and_model_change_invalidate_only_index(db, corpus):
    course, _, chunks = corpus
    provider = FakeEmbedding()
    service = RetrievalService(provider)
    service.index_course(db, course)
    generated_at = db.get(ChunkEmbedding, chunks[1].id).generated_at
    assert service.index_course(db, course)['skipped'] == 3
    chunks[0].content = 'changed'
    db.commit()
    assert len(service.search(db, course, 'q')) == 2
    assert service.index_course(db, course)['generated'] == 1
    assert db.get(ChunkEmbedding, chunks[1].id).generated_at == generated_at
    assert service.search(db, course, 'q')[-1].text == 'changed'
    provider.model_version = '2'
    assert service.search(db, course, 'q') == []
    assert service.index_course(db, course)['generated'] == 3


def test_role_change_does_not_reembed(db, corpus):
    course, _, chunks = corpus
    service = RetrievalService(FakeEmbedding())
    service.index_course(db, course)
    resource = db.get(Resource, chunks[0].resource_id)
    resource.resource_type = ResourceType.tutorial
    db.commit()
    assert service.index_course(db, course)['generated'] == 0
    assert len(service.search(db, course, 'q', resource_types=['tutorial'])) == 2


def test_chunk_replacement_cascades_without_pipeline_change(db, corpus):
    course, _, chunks = corpus
    service = RetrievalService(FakeEmbedding())
    service.index_course(db, course)
    resource_id = chunks[0].resource_id
    replace_chunks(db, resource_id, [DocumentChunkCreate(resource_id=resource_id, page_number=3,
                                                        chunk_index=0, content='changed')])
    db.commit()
    assert db.scalar(select(func.count()).select_from(ChunkEmbedding)) == 2
    assert len(service.search(db, course, 'q')) == 2
    assert service.index_course(db, course)['generated'] == 1


def test_metadata_revision_and_pending_source_are_not_retrieved(db, corpus):
    course, _, chunks = corpus
    service = RetrievalService(FakeEmbedding())
    service.index_course(db, course)
    resource = db.get(Resource, chunks[0].resource_id)
    resource.external_revision = 'new-source'
    db.commit()
    assert len(service.search(db, course, 'q')) == 2
    resource.sync_status = ResourceStatus.pending
    db.commit()
    assert service.index_course(db, course)['unusable'] == 1
    resource.sync_status, resource.sync_stage = ResourceStatus.failed, 'knowledge'
    db.commit()
    assert service.index_course(db, course)['generated'] == 1


def test_corrupt_vector_is_skipped_and_rebuilt(db, corpus):
    service = RetrievalService(FakeEmbedding())
    service.index_course(db, corpus[0])
    db.get(ChunkEmbedding, corpus[2][0].id).embedding = [0., 0.]
    db.commit()
    assert len(service.search(db, corpus[0], 'q')) == 2
    assert service.index_course(db, corpus[0])['generated'] == 1


def test_source_changed_during_indexing_rolls_back(db, corpus):
    provider = FakeEmbedding()
    original = provider.embed
    def change(texts):
        vectors = original(texts)
        chunk = db.get(DocumentChunk, corpus[2][0].id)
        chunk.content = 'changed'
        db.commit()
        return vectors
    provider.embed = change
    with pytest.raises(ValueError, match='Source changed'):
        RetrievalService(provider).index_course(db, corpus[0])
    assert db.scalar(select(func.count()).select_from(ChunkEmbedding)) == 0


def test_bad_provider_response_does_not_persist(db, corpus):
    provider = FakeEmbedding()
    provider.embed = Mock(return_value=[[1., 0.]])
    with pytest.raises(ValueError, match='count'):
        RetrievalService(provider).index_course(db, corpus[0])
    assert db.scalar(select(func.count()).select_from(ChunkEmbedding)) == 0


def test_source_changed_during_query_not_returned(db, corpus):
    course, _, chunks = corpus
    provider = FakeEmbedding()
    service = RetrievalService(provider)
    service.index_course(db, course)
    changed_id = chunks[0].id
    def change(query):
        db.get(DocumentChunk, changed_id).content = 'changed'
        db.commit()
        return [1., 0.]
    provider.embed_query = change
    assert changed_id not in [hit.chunk_id for hit in service.search(db, course, 'q')]


@pytest.mark.parametrize('query,k', [('', 5), ('x'*4001, 5), ('q', 0), ('q', 101)])
def test_query_validation(db, corpus, query, k):
    with pytest.raises(ValueError):
        RetrievalService(FakeEmbedding()).search(db, corpus[0], query, top_k=k)


def test_nonexistent_course_rejected(db):
    with pytest.raises(ValueError, match='Course not found'):
        RetrievalService(FakeEmbedding()).search(db, 9999, 'q')


def test_empty_eval_requires_no_database_or_provider(tmp_path, monkeypatch, capsys):
    path = tmp_path/'gold.json'
    path.write_text('[]')
    monkeypatch.setattr(rag_retrieval, 'existing_engine', Mock(side_effect=AssertionError('No database')))
    assert rag_retrieval.main(['eval', '--course-id', '1', '--dataset', str(path)]) == 0
    assert 'Hit@5: 0/0 (N/A)' in capsys.readouterr().out


def test_eval_metrics():
    rows = [{'question': 'q', 'course_id': 1, 'expected_resource_id': target} for target in [11, 13, 15, 99]]
    report = rag_retrieval.evaluate_questions(rows, lambda *a, **k:
        [SimpleNamespace(resource_id=r) for r in [11, 12, 13, 14, 15]])
    assert report['questions'] == 4 and report['hits'] == {1: 1, 3: 2, 5: 3}


@pytest.mark.parametrize('rows', [{}, [{'question':'q','course_id':2,'expected_resource_id':1}],
    [{'question':'','course_id':1,'expected_resource_id':1}],
    [{'question':'q','course_id':1,'expected_resource_id':True}]])
def test_invalid_eval(tmp_path, rows):
    path = tmp_path/'gold.json'
    path.write_text(json.dumps(rows))
    with pytest.raises(ValueError):
        rag_retrieval.load_questions(path, 1)


def test_local_provider_pools_all_windows_without_storing_new_chunks():
    provider = LocalEmbeddingProvider.__new__(LocalEmbeddingProvider)
    provider.dimensions = 2
    provider._windows = lambda text: iter([('first', 3), ('last', 1)])
    provider.encoder = SimpleNamespace(passage_embed=Mock(return_value=iter([
        SimpleNamespace(tolist=lambda: [1., 0.]), SimpleNamespace(tolist=lambda: [0., 1.]) ])))
    assert provider.embed(['long original chunk'])[0] == pytest.approx(unit_vector([3, 1]))
    provider.encoder.passage_embed.assert_called_once_with(['first', 'last'], batch_size=16)
