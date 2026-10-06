from unittest.mock import Mock

import pytest
from sqlalchemy import delete, select, text

from app.models import ChunkEmbedding, Course, DocumentChunk, Resource, SyncRecord
from app.services.course_index import CourseIndexService, index_course, recover_interrupted_indexes
from app.services.course_qa import CourseQAService
from app.services.rag_answer_service import RAGAnswerService
from app.services.ai_errors import AIConfigurationError
from test_retrieval import FakeEmbedding, corpus
from test_sync import run, sync_setup


def test_initial_repeat_new_changed_and_deleted(db, corpus):
    course, _, chunks = corpus
    provider = FakeEmbedding(); service = CourseIndexService(provider)
    first = service.index_course(db, course)
    assert (first['total_chunks'], first['new_embeddings'], first['updated_embeddings'], first['skipped_embeddings']) == (3, 3, 0, 0)
    assert service.status(db, course)['state'] == 'ready'
    second = service.index_course(db, course)
    assert (second['new_embeddings'], second['updated_embeddings'], second['skipped_embeddings']) == (0, 0, 3)
    assert len(provider.inputs) == 3
    db.add(DocumentChunk(resource_id=chunks[0].resource_id, page_number=3, chunk_index=1, content='first'))
    db.commit()
    assert service.index_course(db, course)['new_embeddings'] == 1
    chunks[0].content = 'changed'; db.commit()
    assert service.status(db, course)['state'] == 'stale'
    result = service.index_course(db, course)
    assert (result['updated_embeddings'], result['skipped_embeddings']) == (1, 3)
    removed_id = chunks[1].id
    db.execute(delete(DocumentChunk).where(DocumentChunk.id == removed_id)); db.commit()
    assert db.get(ChunkEmbedding, removed_id) is None  # FK CASCADE cleans immediately.
    assert service.index_course(db, course)['total_chunks'] == 3


def test_unusable_cleanup_and_other_course_untouched(db, corpus):
    a, b, chunks = corpus
    service = CourseIndexService(FakeEmbedding())
    service.index_course(db, a); service.index_course(db, b)
    foreign_time = db.get(ChunkEmbedding, chunks[-1].id).generated_at
    resource = db.get(Resource, chunks[0].resource_id)
    resource.sync_status = 'pending'; db.commit()
    assert service.index_course(db, a)['removed_stale'] == 1
    assert db.get(ChunkEmbedding, chunks[-1].id).generated_at == foreign_time


@pytest.mark.parametrize('field,value', [('model','another-model'),('model_version','2')])
def test_incompatible_model_or_version_is_not_reused(db, corpus, field, value):
    provider = FakeEmbedding(); service = CourseIndexService(provider)
    service.index_course(db, corpus[0])
    setattr(provider, field, value)
    assert service.status(db, corpus[0])['state'] == 'stale'
    assert service.index_course(db, corpus[0])['updated_embeddings'] == 3


def test_missing_or_corrupt_embeddings_cannot_be_ready(db, corpus):
    service = CourseIndexService(FakeEmbedding()); course = corpus[0]
    assert service.status(db, course)['state'] == 'stale'
    service.index_course(db, course)
    row = db.get(ChunkEmbedding, corpus[2][0].id); row.embedding = [0,0]; db.commit()
    assert service.status(db, course)['missing_chunks'] == 1
    assert service.index_course(db, course)['updated_embeddings'] == 1
    db.delete(row); db.commit()
    assert service.status(db, course)['state'] == 'stale'


def test_legacy_orphan_cleanup(db, engine, corpus):
    service = CourseIndexService(FakeEmbedding()); service.index_course(db, corpus[0])
    db.commit()
    with engine.connect() as connection:
        connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
        connection.exec_driver_sql("UPDATE chunk_embeddings SET chunk_id=99999 WHERE chunk_id=?", (corpus[2][0].id,))
        connection.commit()
        connection.exec_driver_sql('PRAGMA foreign_keys=ON')
    db.expire_all()
    result = service.index_course(db, corpus[0])
    assert result['removed_stale'] == 1 and result['new_embeddings'] == 1


def test_existing_index_claim_not_overwritten(db, corpus):
    course = db.get(Course, corpus[0]); course.indexing_report = {'state':'indexing'}; db.commit()
    service = CourseIndexService(FakeEmbedding())
    with pytest.raises(ValueError, match='already'): service.index_course(db, course.id)
    assert course.indexing_report == {'state':'indexing'}


def test_course_report_additive_upgrade_preserves_legacy_rows():
    from app.core.database import build_engine
    from app.core.schema_upgrade import upgrade_sync_columns
    engine = build_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE courses (id INTEGER PRIMARY KEY, name TEXT)'))
        connection.execute(text("INSERT INTO courses VALUES (1, 'Example')"))
    upgrade_sync_columns(engine); upgrade_sync_columns(engine)
    with engine.connect() as connection:
        assert connection.execute(text('SELECT id,name,indexing_report FROM courses')).one() == (1,'Example',None)
    engine.dispose()


def test_shared_index_strict_course_isolation(db, corpus):
    service = CourseIndexService(FakeEmbedding())
    for course in corpus[:2]: service.index_course(db, course)
    for course in corpus[:2]:
        results = service.retrieval.search(db, course, 'query')
        assert results and all(hit.course_id == course for hit in results)
    assert len(db.scalars(select(ChunkEmbedding)).all()) == 4


def test_failure_preserves_data_and_successful_batches(db, corpus):
    provider = FakeEmbedding(); service = CourseIndexService(provider)
    original = provider.embed
    calls = 0
    def embed(texts):
        nonlocal calls
        calls += 1
        if calls == 2: raise RuntimeError('private provider details')
        return original(texts)
    provider.embed = embed
    original_index = service.retrieval.index_course
    service.retrieval.index_course = lambda db, cid: original_index(db, cid, batch_size=1)
    with pytest.raises(RuntimeError): service.index_course(db, corpus[0])
    assert len(db.scalars(select(DocumentChunk)).all()) == 4
    assert len(db.scalars(select(ChunkEmbedding)).all()) == 1
    assert service.status(db, corpus[0])['state'] == 'error'
    assert 'private' not in str(db.get(Course, corpus[0]).indexing_report)


def test_index_failure_isolated_from_successful_sync(db, sync_setup):
    indexer = Mock(side_effect=RuntimeError('private error'))
    sync_setup[0].indexer = indexer
    result = run(db, sync_setup)
    assert result.status == 'completed' and result.files_failed == 0
    assert db.scalar(select(DocumentChunk)) is not None
    assert list(result.details['indexing'].values())[0]['state'] == 'error'
    assert 'private error' not in str(result.details)
    indexer.assert_called_once()


def test_dry_run_does_not_index_and_unchanged_sync_does(db, sync_setup):
    def indexed(session, course_id):
        record = session.scalar(select(SyncRecord).order_by(SyncRecord.id.desc()))
        assert record.status == 'running' and record.details['progress']['stage'] == 'indexing'
        return {'skipped_embeddings':1}
    indexer = Mock(side_effect=indexed)
    sync_setup[0].indexer = indexer
    run(db, sync_setup, dry_run=True); indexer.assert_not_called()
    run(db, sync_setup); run(db, sync_setup)
    assert indexer.call_count == 2


def test_recover_indexing_and_model_load_failure(db, corpus, monkeypatch):
    course = db.get(Course, corpus[0]); course.indexing_report = {'state':'indexing'}; db.commit()
    recover_interrupted_indexes(db)
    assert course.indexing_report['state'] == 'error'
    monkeypatch.setattr('app.services.course_index.local_embedding', Mock(side_effect=RuntimeError('private cache path')))
    with pytest.raises(RuntimeError): index_course(db, course.id)
    assert course.indexing_report['state'] == 'error'
    assert 'private' not in str(course.indexing_report)


def test_status_endpoint_and_ready_qa(db, corpus, client, monkeypatch):
    provider = FakeEmbedding(); index = CourseIndexService(provider)
    course = corpus[0]; index.index_course(db, course)
    monkeypatch.setattr('app.services.course_index.local_embedding', lambda:provider)
    status = client.get(f'/api/courses/{course}/index-status')
    assert status.status_code == 200 and status.json()['state'] == 'ready'
    reranker = Mock(); reranker.score.side_effect = lambda q, texts: [1.0]*len(texts)
    runtime = RAGAnswerService(index.retrieval, reranker)
    monkeypatch.setattr('app.services.course_qa._runtime', lambda:runtime)
    llm = Mock(); llm.generate.return_value = '{"answerable":true,"answer":"A supported statement [1].","citation_ids":[1]}'
    monkeypatch.setattr('app.services.course_qa.create_llm_provider', lambda _:llm)
    answer = CourseQAService().ask(db, course, 'query')
    assert answer.sources and all(s.course_id == course for s in answer.sources)
    llm.generate.assert_called_once()
    db.delete(db.get(ChunkEmbedding, corpus[2][0].id)); db.commit()
    with pytest.raises(AIConfigurationError): CourseQAService().ask(db, course, 'query')
    assert llm.generate.call_count == 1


def test_source_changes_during_generation_fail_closed(db, corpus, monkeypatch):
    index = CourseIndexService(FakeEmbedding()); index.index_course(db, corpus[0])
    reranker = Mock(); reranker.score.side_effect = lambda q, texts:[1.0]*len(texts)
    runtime = RAGAnswerService(index.retrieval, reranker)
    monkeypatch.setattr('app.services.course_qa._runtime', lambda:runtime)
    def generate(*args):
        corpus[2][0].content = 'changed'; db.commit()
        return '{"answerable":true,"answer":"A supported statement [1].","citation_ids":[1]}'
    llm = Mock(); llm.generate.side_effect = generate
    monkeypatch.setattr('app.services.course_qa.create_llm_provider', lambda _:llm)
    with pytest.raises(AIConfigurationError): CourseQAService().ask(db, corpus[0], 'query')


def test_backfill_ready_new_empty_and_changed(db, corpus, monkeypatch):
    from app.index_course import backfill
    provider = FakeEmbedding()
    monkeypatch.setattr('app.services.course_index.local_embedding', lambda: provider)
    index_course(db, corpus[0])
    saved = db.get(ChunkEmbedding, corpus[2][0].id).generated_at
    db.add(Course(semester_id=db.get(Course, corpus[0]).semester_id, code='EMPTY', name='Empty'))
    db.commit()
    result = backfill(db)
    assert (result['courses'], result['ready_before'], result['ready'], result['newly_indexed'],
            result['stale_updated'], result['unavailable'], result['errors']) == (3, 1, 2, 1, 0, 1, 0)
    assert (result['new_embeddings'], result['updated_embeddings'], result['skipped_embeddings']) == (1, 0, 3)
    assert len(provider.inputs) == 4
    assert db.get(ChunkEmbedding, corpus[2][0].id).generated_at == saved
    corpus[2][0].content = 'changed'; db.commit()
    result = backfill(db)
    assert (result['newly_indexed'], result['stale_updated'], result['updated_embeddings'], result['skipped_embeddings']) == (0, 1, 1, 3)
    result = backfill(db)
    assert result['ready_before'] == 2 and result['skipped_embeddings'] == 4
    assert result['new_embeddings'] == result['updated_embeddings'] == 0
    assert len(provider.inputs) == 5


def test_backfill_error_continues_and_does_not_expose_provider_details(db, corpus, monkeypatch, capsys):
    from app.index_course import backfill
    provider = FakeEmbedding()
    embed = provider.embed
    def fail_first(texts):
        if 'first' in texts:
            raise RuntimeError('SECRET provider details')
        return embed(texts)
    provider.embed = fail_first
    monkeypatch.setattr('app.services.course_index.local_embedding', lambda: provider)
    result = backfill(db)
    assert result['errors'] == 1 and result['ready'] == 1
    assert [r['state'] for r in result['results']] == ['error', 'ready']
    assert db.get(Course, corpus[0]).indexing_report['state'] == 'error'
    assert len(db.scalars(select(DocumentChunk)).all()) == 4
    assert 'SECRET' not in capsys.readouterr().out


def test_backfill_empty_database_and_cli_scope(engine, db, monkeypatch, capsys):
    from app import index_course as cli
    assert cli.backfill(db)['courses'] == 0
    db.close()  # CLI owns engine disposal; release the fixture's read transaction first.
    monkeypatch.setattr(cli, 'build_engine', lambda _: engine)
    assert cli.main(['--all']) == 0
    assert '"courses": 0' in capsys.readouterr().out
    for args in ([], ['--all', '--course-id', '1'], ['--all', '--status']):
        with pytest.raises(SystemExit) as exc:
            cli.main(args)
        assert exc.value.code == 2
