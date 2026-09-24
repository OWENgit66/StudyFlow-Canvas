from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from unittest.mock import Mock

import pymupdf
import pytest
from sqlalchemy import select, func, text

from app.core.config import Settings
from app.models import Course, Week, Semester, Resource, SyncRecord, ResourceKnowledge, DocumentChunk, Summary
from app.schemas.canvas import CanvasCourse, CanvasModule, CanvasModuleItem, CanvasFile
from app.schemas.sync import SyncRequest
from app.services.sync_service import SyncService, _sync_lock, SyncBusyError
from app.services.document_service import DocumentService
from app.services.knowledge_service import KnowledgeService
from app.services.ai_errors import AITransientError, KnowledgeNotFoundError
from app.services.material_paths import build_material_path
from app.services.canvas_storage import save_stream
from app.api.sync import get_sync_service
from app.api.knowledge import get_knowledge_service
from test_knowledge import FakeProvider, ai


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def pdf_bytes(content='Frames carry data.'):
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 100), content)
        return pdf.tobytes()


class MockCanvas:
    def __init__(self, root):
        self.root = root
        self.courses = [CanvasCourse(id=1001, name='Networks', course_code='COMP', enrollment_term_id=101)]
        self.modules = [CanvasModule(id=51, name='Network Layer', position=1)]
        self.metadata = {201: CanvasFile(id=201, filename='lecture.pdf', size=10, updated_at=NOW)}
        self.contents = {201: pdf_bytes()}
        self.downloads = []
        self.fail_download = set()
        self.get_courses = Mock(side_effect=lambda: self.courses)
        self.get_modules = Mock(side_effect=lambda _: self.modules)
        self.get_module_items = Mock(side_effect=lambda c, m: [CanvasModuleItem(
            id=i, module_id=m, title=f.filename, type='File', content_id=i) for i,f in self.metadata.items()])
        self.get_file = Mock(side_effect=lambda i: self.metadata[i])

    def __enter__(self): return self
    def __exit__(self, *_): pass

    def download_file(self, file_id, *, context, existing_path=None):
        self.downloads.append(file_id)
        if file_id in self.fail_download:
            raise RuntimeError('PRIVATE_SECRET must never appear in sync errors')
        target = build_material_path(self.root, context, self.metadata[file_id].filename)
        content = self.contents[file_id]
        return save_stream(self.root, target, [content], len(content), 1000000, existing_path=existing_path)


@pytest.fixture
def sync_setup(db, tmp_path):
    db.add(Semester(name='Current semester', year=2027, term='S1', is_active=True, canvas_term_id=101))
    db.commit()
    settings = Settings(_env_file=None, materials_root=tmp_path/'materials')
    canvas = MockCanvas(settings.materials_root)
    documents = DocumentService(settings)
    documents.parse = Mock(wraps=documents.parse)
    knowledge = KnowledgeService(documents)
    provider = FakeProvider()
    factory = Mock(side_effect=lambda: ai(provider))
    service = SyncService(settings, lambda:canvas, documents, knowledge, factory)
    return service, canvas, documents, knowledge, provider, factory


def run(db, setup, **kwargs):
    return setup[0].run(db, SyncRequest(), **kwargs)


def test_full_mocked_workflow_and_unchanged_second_sync(db, sync_setup):
    service, canvas, documents, knowledge, provider, factory = sync_setup
    first = run(db, sync_setup)
    assert first.status == 'completed'
    assert (first.courses_processed, first.files_discovered, first.files_downloaded,
            first.files_updated, first.files_failed) == (1,1,1,0,0)
    assert first.details['files_parsed'] == first.details['files_analyzed'] == 1
    resource = db.scalar(select(Resource))
    assert resource.sync_status == 'completed' and resource.sync_stage == 'done'
    assert resource.week.canvas_module_id == 51 and resource.week.title == 'Network Layer'
    assert resource.week.course.canvas_course_id == 1001
    assert '2027-S1' in resource.local_path
    assert knowledge.read(db, resource.id).stale is False
    assert db.scalar(select(func.count()).select_from(DocumentChunk)) == 1
    original = db.scalar(select(DocumentChunk)).id
    calls = (len(canvas.downloads), documents.parse.call_count, factory.call_count, len(provider.calls))
    second = run(db, sync_setup)
    assert second.files_skipped == 1 and second.files_downloaded == 0
    assert calls == (len(canvas.downloads), documents.parse.call_count, factory.call_count, len(provider.calls))
    assert db.scalar(select(DocumentChunk)).id == original
    for model in [Course, Week, Resource, ResourceKnowledge]:
        assert db.scalar(select(func.count()).select_from(model)) == 1
    assert len(list(canvas.root.rglob('*.pdf'))) == 1


def test_updated_same_resource_replaces_chunks_and_knowledge(db, sync_setup):
    run(db, sync_setup)
    resource = db.scalar(select(Resource)); resource_id = resource.id
    before = sync_setup[3].read(db, resource_id).source_fingerprint
    sync_setup[1].metadata[201].updated_at += timedelta(days=1)
    sync_setup[1].contents[201] = pdf_bytes('Frames carry new data.')
    result = run(db, sync_setup)
    assert result.files_updated == result.files_downloaded == 1
    assert db.scalar(select(Resource)).id == resource_id
    assert 'new data' in db.scalar(select(DocumentChunk)).content
    current = sync_setup[3].read(db, resource_id)
    assert not current.stale and current.source_fingerprint != before
    assert len(list(sync_setup[1].root.rglob('*.pdf'))) == 1


@pytest.mark.parametrize('stage', ['download','parse','knowledge'])
def test_failure_isolated_retry_correct_stage(db, sync_setup, stage, caplog):
    service, canvas, documents, knowledge, provider, factory = sync_setup
    canvas.metadata[202] = CanvasFile(id=202, filename='other.pdf', size=10, updated_at=NOW)
    canvas.contents[202] = pdf_bytes()
    if stage == 'download': canvas.fail_download.add(201)
    if stage == 'parse': canvas.contents[201] = b'not PDF'
    if stage == 'knowledge':
        provider.responses = [AITransientError('PRIVATE_SECRET')]*2
    result = run(db, sync_setup)
    assert result.status == 'completed_with_errors' and result.files_failed == 1
    assert result.details['errors'][0]['stage'] == ('generation' if stage == 'knowledge' else stage)
    assert 'PRIVATE_SECRET' not in result.model_dump_json() + caplog.text
    resources = db.scalars(select(Resource).order_by(Resource.canvas_file_id)).all()
    failed, success = resources
    assert failed.sync_status == 'failed' and success.sync_status == 'completed'
    assert db.scalar(select(SyncRecord).where(SyncRecord.id==result.id)).completed_at is not None
    if stage == 'knowledge':
        chunk_id = db.scalar(select(DocumentChunk.id).where(DocumentChunk.resource_id==failed.id))
        downloads = len(canvas.downloads)
        second = run(db, sync_setup)
        assert second.status == 'completed' and second.files_skipped == 1
        assert second.files_downloaded == second.details['files_parsed'] == 0
        assert len(canvas.downloads) == downloads
        assert db.scalar(select(DocumentChunk.id).where(DocumentChunk.resource_id==failed.id)) == chunk_id
    assert db.execute(text('PRAGMA foreign_key_check')).all() == []


@pytest.mark.parametrize('failure', ['download','parse','knowledge'])
def test_updated_failure_never_exposes_old_knowledge_as_current(db, sync_setup, failure):
    run(db, sync_setup)
    resource = db.scalar(select(Resource))
    before = db.get(ResourceKnowledge, resource.id).payload
    canvas = sync_setup[1]
    canvas.metadata[201].updated_at += timedelta(days=1)
    if failure == 'download': canvas.fail_download.add(201)
    if failure == 'parse': canvas.contents[201] = b'broken'
    if failure == 'knowledge': sync_setup[4].responses = [AITransientError('test')]*2
    result = run(db, sync_setup)
    assert result.files_failed == 1
    with pytest.raises(KnowledgeNotFoundError): sync_setup[3].read(db, resource.id)
    assert sync_setup[3].read(db, resource.id, include_stale=True).stale
    assert db.get(ResourceKnowledge, resource.id).payload == before
    assert db.scalar(select(Summary)).key_points == []


def test_stale_api_default_and_explicit_history(client, db, sync_setup):
    run(db, sync_setup)
    resource = db.scalar(select(Resource))
    db.scalar(select(DocumentChunk)).content = 'Changed'
    db.commit()
    client.app.dependency_overrides[get_knowledge_service] = lambda:sync_setup[3]
    assert client.get(f'/api/resources/{resource.id}/knowledge').status_code == 404
    result = client.get(f'/api/resources/{resource.id}/knowledge?include_stale=true')
    assert result.status_code == 200 and result.json()['stale'] is True


def test_unsupported_file_downloaded_without_parser_or_ai(db, sync_setup):
    canvas = sync_setup[1]
    canvas.metadata[201].filename = 'slides.pptx'
    result = run(db, sync_setup)
    assert result.status == 'completed' and result.files_downloaded == 1
    assert sync_setup[2].parse.call_count == sync_setup[5].call_count == 0
    assert db.scalar(select(Resource)).sync_stage == 'unsupported'
    assert run(db, sync_setup).files_skipped == 1


def test_module_identity_survives_renaming_reordering_and_shared_file(db, sync_setup):
    run(db, sync_setup)
    week_id = db.scalar(select(Week)).id
    canvas = sync_setup[1]
    canvas.modules[0].name = 'Revision'
    canvas.modules[0].position = 9
    canvas.modules.append(CanvasModule(id=52, name='Module 2', position=2))
    result = run(db, sync_setup)
    assert result.files_discovered == 1 and result.files_skipped == 1
    assert db.get(Week, week_id).title == 'Revision'
    assert db.scalar(select(func.count()).select_from(Resource)) == 1


def test_sync_api_and_status(client, db, sync_setup):
    client.app.dependency_overrides[get_sync_service] = lambda:sync_setup[0]
    response = client.post('/api/sync')
    assert response.status_code == 200 and response.json()['status'] == 'completed'
    record = client.get('/api/sync/'+str(response.json()['id']))
    assert record.json() == response.json()
    assert client.get('/api/sync/999').status_code == 404
    assert client.post('/api/sync', json={'file_id':201}).status_code == 422
    assert client.get('/health').status_code == 200


def test_dry_run_discovers_without_catalog_or_source_mutations(db, sync_setup):
    result = run(db, sync_setup, dry_run=True)
    assert result.status == 'completed'
    assert result.details['events'][0]['outcome'] == 'NEW'
    for model in (Resource, Course, Week, ResourceKnowledge):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    assert sync_setup[1].downloads == [] and sync_setup[5].call_count == 0


def test_multiple_semesters_defaults_to_active_and_rejects_other_selection(db, sync_setup):
    second = Semester(name='Second',year=2028,term='S2'); db.add(second); db.commit()
    result = run(db, sync_setup)
    assert result.status == 'completed'
    assert db.scalar(select(Course)).semester_id != second.id
    with pytest.raises(ValueError, match='active semester'):
        sync_setup[0].run(db, SyncRequest(semester_id=second.id))


def test_discovery_failure_is_safe_terminal_record(db, sync_setup):
    sync_setup[1].get_courses.side_effect = RuntimeError('PRIVATE_SECRET')
    result = run(db, sync_setup)
    assert result.status == 'failed' and result.completed_at
    assert result.details['errors'][0]['stage'] == 'discovery'
    assert 'PRIVATE_SECRET' not in result.model_dump_json()


def test_overlapping_sync_rejected(db, sync_setup):
    with _sync_lock:
        with pytest.raises(SyncBusyError): run(db, sync_setup)


def test_completed_resource_with_old_resume_marker_does_not_repeat_ai(db, sync_setup):
    run(db, sync_setup)
    db.scalar(select(Resource)).sync_stage = 'knowledge'
    db.commit()
    sync_setup[5].side_effect = AssertionError('Provider must not be initialized')
    assert run(db, sync_setup).files_skipped == 1


def test_download_failure_retries_same_resource(db, sync_setup):
    canvas = sync_setup[1]
    canvas.fail_download.add(201)
    assert run(db, sync_setup).files_failed == 1
    resource_id = db.scalar(select(Resource)).id
    canvas.fail_download.clear()
    assert run(db, sync_setup).status == 'completed'
    assert db.scalar(select(Resource)).id == resource_id
    assert len(list(canvas.root.rglob('*.pdf'))) == 1


def test_parse_failure_retries_parse_without_download(db, sync_setup):
    original = sync_setup[2].parse.side_effect
    sync_setup[2].parse.side_effect = RuntimeError('Temporary parser problem')
    assert run(db, sync_setup).files_failed == 1
    sync_setup[2].parse.side_effect = original
    second = run(db, sync_setup)
    assert second.status == 'completed' and second.files_downloaded == 0
    assert len(sync_setup[1].downloads) == 1


def test_scoped_single_file_ignores_other_modules_and_files(db, sync_setup):
    run(db, sync_setup)
    course = db.scalar(select(Course))
    canvas = sync_setup[1]
    canvas.metadata[202] = CanvasFile(id=202, filename='not-requested.pdf', size=10, updated_at=NOW)
    canvas.modules.append(CanvasModule(id=52, name='Other', position=2))
    canvas.get_module_items.reset_mock()
    result = sync_setup[0].run(db, SyncRequest(course_id=course.id, module_id=51, file_id=201))
    assert result.files_discovered == result.files_skipped == 1
    canvas.get_module_items.assert_called_once_with(1001,51)
    assert canvas.get_file.call_args.args == (201,)


def test_missing_scoped_file_records_discovery_error(db, sync_setup):
    run(db, sync_setup)
    result = sync_setup[0].run(db, SyncRequest(course_id=db.scalar(select(Course.id)), module_id=51, file_id=999))
    assert result.status == 'completed_with_errors'
    assert result.details['errors'][0]['file_id'] == 999


def test_module_discovery_failure_does_not_stop_next_module(db, sync_setup):
    canvas = sync_setup[1]
    canvas.modules.insert(0, CanvasModule(id=50,name='Broken',position=0))
    original = canvas.get_module_items.side_effect
    canvas.get_module_items.side_effect = lambda c,m: (_ for _ in ()).throw(RuntimeError()) if m==50 else original(c,m)
    result = run(db, sync_setup)
    assert result.status == 'completed_with_errors' and result.files_downloaded == 1


def test_same_name_different_canvas_files_keep_separate_paths(db, sync_setup):
    canvas = sync_setup[1]
    canvas.metadata[202] = CanvasFile(id=202,filename='lecture.pdf',size=10,updated_at=NOW)
    canvas.contents[202] = pdf_bytes()
    assert run(db, sync_setup).files_downloaded == 2
    paths = [r.local_path for r in db.scalars(select(Resource))]
    assert len(set(paths)) == 2
    assert run(db, sync_setup).files_skipped == 2
    assert len(list(canvas.root.rglob('*.pdf'))) == 2


def test_missing_timestamp_does_not_falsely_classify_or_call_ai(db, sync_setup):
    sync_setup[1].metadata[201].updated_at = None
    result = run(db, sync_setup)
    assert result.files_failed == 1 and result.files_skipped == 0
    assert sync_setup[1].downloads == [] and sync_setup[5].call_count == 0


def test_unchanged_stale_result_skipped_without_paid_repair(db, sync_setup):
    run(db, sync_setup)
    row = db.scalar(select(ResourceKnowledge)); row.source_fingerprint = 'old-pipeline'; db.commit()
    sync_setup[5].side_effect = AssertionError('No paid repair during unchanged sync')
    result = run(db, sync_setup)
    assert result.files_skipped == 1
    with pytest.raises(KnowledgeNotFoundError): sync_setup[3].read(db,row.resource_id)


def test_week_summary_excludes_stale_sibling_resource(db, sync_setup):
    run(db, sync_setup)
    old = db.scalar(select(ResourceKnowledge)); old.source_fingerprint='historical'; db.commit()
    canvas=sync_setup[1]
    canvas.metadata[202]=CanvasFile(id=202,filename='other.pdf',size=10,updated_at=NOW)
    canvas.contents[202]=pdf_bytes()
    assert run(db,sync_setup).status=='completed'
    summary=db.scalar(select(Summary))
    assert f'Resource {old.resource_id}:' not in summary.overview
    assert len(summary.key_points)==1


def test_dry_run_updated_does_not_invalidate_existing_result(db,sync_setup):
    run(db,sync_setup)
    before=db.scalar(select(ResourceKnowledge)).payload
    sync_setup[1].metadata[201].updated_at += timedelta(days=1)
    result=run(db,sync_setup,dry_run=True)
    assert result.details['events'][0]['outcome']=='UPDATED'
    assert db.scalar(select(ResourceKnowledge)).payload==before
    assert sync_setup[3].read(db,db.scalar(select(Resource.id))).stale is False


def test_usage_aggregates_returned_values_without_invented_tokens(db,sync_setup):
    result=run(db,sync_setup)
    assert result.details['usage']['requests']>=2
    assert 'total_tokens' not in result.details['usage']  # Mock returns no API usage.


def test_additive_schema_upgrade_is_idempotent_and_preserves_legacy_rows(tmp_path):
    from app.core.database import build_engine, init_db
    from app.core.schema_upgrade import upgrade_sync_columns
    from sqlalchemy import inspect
    engine=build_engine('sqlite:///'+str(tmp_path/'legacy.db'))
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE weeks (id INTEGER PRIMARY KEY, course_id INTEGER, title TEXT)')
        connection.exec_driver_sql("INSERT INTO weeks VALUES (1,2,'Legacy')")
        connection.exec_driver_sql('CREATE TABLE resources (id INTEGER PRIMARY KEY)')
        connection.exec_driver_sql('CREATE TABLE sync_records (id INTEGER PRIMARY KEY)')
        connection.exec_driver_sql('INSERT INTO sync_records VALUES (1)')
    upgrade_sync_columns(engine); upgrade_sync_columns(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT title,canvas_module_id FROM weeks').one()==('Legacy',None)
        assert connection.exec_driver_sql('SELECT details FROM sync_records').scalar_one()=='{}'
        assert 'sync_stage' in {c['name'] for c in inspect(connection).get_columns('resources')}
    engine.dispose()


def test_running_record_is_visible_before_download(db,sync_setup):
    canvas=sync_setup[1]
    original=canvas.download_file
    def checked(*args,**kwargs):
        record=db.scalar(select(SyncRecord))
        assert record.status=='running' and record.started_at and record.completed_at is None
        assert record.files_discovered==1
        return original(*args,**kwargs)
    canvas.download_file=checked
    assert run(db,sync_setup).status=='completed'


def test_legacy_week_adoption_and_course_metadata_update(db,sync_setup):
    semester=db.scalar(select(Semester))
    course=Course(semester_id=semester.id,canvas_course_id=1001,code='OLD',name='Old name')
    week=Week(course=course,week_number=1,title='Network Layer')
    db.add(week);db.commit()
    assert run(db,sync_setup).status=='completed'
    assert db.scalar(select(func.count()).select_from(Week))==1
    assert week.canvas_module_id==51 and course.code=='COMP' and course.name=='Networks'


@pytest.mark.parametrize('kind', ['Assignment', 'Quiz', 'ExternalUrl', 'ExternalTool', 'Discussion', 'SubHeader'])
def test_non_material_module_items_are_ignored(db,sync_setup,kind):
    canvas=sync_setup[1]
    canvas.get_module_items.side_effect=lambda c,m:[CanvasModuleItem(id=1,module_id=m,title=kind,type=kind,content_id=201)]
    result=run(db,sync_setup)
    assert result.status=='completed' and result.files_discovered==0
    canvas.get_file.assert_not_called()


def test_reported_usage_is_allowlisted_and_partial_totals_are_identifiable():
    from types import SimpleNamespace
    record=SyncRecord(details={'usage':{}})
    service_ai=SimpleNamespace(request_counts={'generation':2,'semantic_validation':1},usage=[
        {'prompt_tokens':10,'completion_tokens':4,'total_tokens':14,'Authorization':'PRIVATE_SECRET'},
        {'stage':'generation'}, {'prompt_tokens':2,'completion_tokens':1,'total_tokens':3}])
    SyncService._usage(record,service_ai)
    assert record.details['usage']=={'requests':3,'requests_with_token_usage':2,
                                     'prompt_tokens':12,'completion_tokens':5,'total_tokens':17}
    assert 'PRIVATE_SECRET' not in json.dumps(record.details)
