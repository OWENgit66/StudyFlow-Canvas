"""A/B isolation tests with synthetic vectors; no downloads or private data."""
import json
import sqlite3

import pytest
from sqlalchemy import select

from app.core.database import build_engine, create_session_factory, init_db
from app.models import Course, Semester, Week, Resource, DocumentChunk, ChunkEmbedding
from app.models.common import ResourceStatus
from app.services.retrieval_service import RetrievalService
from evals.retrieval_ab import create_course_snapshot, snapshot_digest, file_hash, compare_reports
from evals.rag_retrieval import evaluate_questions


class Provider:
    dimensions = 2
    model_version = 'version-1'
    window_tokens = 96

    def __init__(self, model):
        self.model = model

    def embed(self, texts):
        return [[1., 0.] if self.model == 'a' else [0., 1.] for _ in texts]

    def embed_query(self, text):
        return [1., 0.]


@pytest.fixture
def corpus_file(tmp_path):
    path = tmp_path/'source.sqlite'
    engine = build_engine('sqlite:///' + path.as_posix())
    init_db(engine)
    with create_session_factory(engine)() as db:
        semester = Semester(name='Synthetic term', year=2026, term='S1')
        courses = [Course(semester=semester, code=f'DEMO{i}', name='Synthetic') for i in range(2)]
        for course in courses:
            resource = Resource(week=Week(course=course, week_number=1, title='Example'),
                                filename='Synthetic.pdf', file_type='pdf', sync_status=ResourceStatus.parsed)
            db.add(DocumentChunk(resource=resource, page_number=2, chunk_index=0, content='Synthetic evidence'))
        db.commit()
        ids = [c.id for c in courses]
        for cid in ids:
            RetrievalService(Provider('a')).index_course(db, cid)
    engine.dispose()
    return path, ids


def test_independent_model_indexes_preserve_original_and_scope(corpus_file, tmp_path):
    original, ids = corpus_file
    original_hash = file_hash(original)
    a, b = tmp_path/'a.sqlite', tmp_path/'b.sqlite'
    counts = create_course_snapshot(original, a, ids[0], include_embeddings=True)
    assert counts['courses'] == counts['document_chunks'] == counts['chunk_embeddings'] == 1
    index_a = snapshot_digest(a, embeddings=True)
    assert create_course_snapshot(a, b, ids[0], include_embeddings=False)['chunk_embeddings'] == 0
    assert snapshot_digest(a) == snapshot_digest(b)
    engine = build_engine('sqlite:///' + b.as_posix())
    with create_session_factory(engine)() as db:
        assert RetrievalService(Provider('b')).index_course(db, ids[0])['generated'] == 1
        assert db.scalar(select(ChunkEmbedding)).model == 'b'
        assert RetrievalService(Provider('b')).search(db, ids[0], 'q')[0].score == 0
        assert RetrievalService(Provider('a')).search(db, ids[0], 'q') == []
        with pytest.raises(ValueError, match='Course not found'):
            RetrievalService(Provider('b')).search(db, ids[1], 'q')
    engine.dispose()
    assert file_hash(original) == original_hash
    assert snapshot_digest(a, embeddings=True) == index_a
    assert snapshot_digest(a) == snapshot_digest(b)
    with sqlite3.connect(b) as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)


def test_snapshot_refuses_overwrite(corpus_file, tmp_path):
    original, ids = corpus_file
    before = file_hash(original)
    with pytest.raises(ValueError):
        create_course_snapshot(original, original, ids[0], include_embeddings=False)
    existing = tmp_path/'occupied.sqlite'
    existing.write_bytes(b'keep me')
    with pytest.raises(FileExistsError):
        create_course_snapshot(original, existing, ids[0], include_embeddings=False)
    assert existing.read_bytes() == b'keep me'
    assert file_hash(original) == before


def test_missing_course_does_not_create_snapshot(corpus_file, tmp_path):
    original, _ = corpus_file
    out = tmp_path/'missing.sqlite'
    with pytest.raises(ValueError, match='Course not found'):
        create_course_snapshot(original, out, 9999, include_embeddings=False)
    assert not out.exists()


def test_comparison_reports_regressions_without_changing_eval():
    from types import SimpleNamespace
    gold = [{'sample_id':'example', 'question':'q', 'course_id':1,
             'expected_resource_id':10, 'expected_pages':[2]}]
    a = evaluate_questions(gold, lambda *a, **k:[SimpleNamespace(resource_id=10, page_number=2)])
    b = evaluate_questions(gold, lambda *a, **k:[SimpleNamespace(resource_id=10, page_number=1)])
    changes = compare_reports(a, b)
    assert len(changes) == 3
    assert all(c['regression'] and c['metric'].startswith('evidence') for c in changes)
    b['results'][0]['expected_pages'] = [3]
    with pytest.raises(ValueError, match='identical'):
        compare_reports(a, b)


def test_runner_uses_frozen_gold_and_only_indexes_b(corpus_file, tmp_path, monkeypatch):
    from evals import retrieval_ab
    source, ids = corpus_file
    with sqlite3.connect(source) as db:
        rid = db.execute('SELECT id FROM resources ORDER BY id LIMIT 1').fetchone()[0]
    gold = tmp_path/'gold.json'
    gold.write_text(json.dumps([{'question':'q', 'course_id':ids[0],
                                'expected_resource_id':rid, 'expected_pages':[2]}]))
    monkeypatch.setattr(retrieval_ab, 'DEFAULT_MODEL', 'a')
    monkeypatch.setattr(retrieval_ab, 'MULTILINGUAL_MODEL', 'b')
    def factory(*, model, allow_download):
        assert allow_download is False
        return Provider(model)
    monkeypatch.setattr(retrieval_ab, 'LocalEmbeddingProvider', factory)
    before = file_hash(source), file_hash(gold)
    output = tmp_path/'experiment'
    report = retrieval_ab.run(source, gold, output, ids[0])
    assert report['profiles']['A']['document_embeddings'] == 0
    assert report['profiles']['B']['document_embeddings'] == 1
    assert report['profiles']['A']['query_embeddings'] == report['profiles']['B']['query_embeddings'] == 1
    assert report['profiles']['A']['index_file'] != report['profiles']['B']['index_file']
    assert (output/'comparison.json').is_file()
    assert before == (file_hash(source), file_hash(gold))
    with pytest.raises(FileExistsError):
        retrieval_ab.run(source, gold, output, ids[0])
