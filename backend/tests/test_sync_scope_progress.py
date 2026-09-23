from threading import Event, Thread

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import create_session_factory
from app.models import Course, Resource, Semester, SyncRecord
from app.schemas.canvas import CanvasCourse
from app.schemas.sync import SyncRequest
from app.services.semester_scope import exclusion_reason
from app.services.sync_service import request_cancellation, recover_interrupted
from test_sync import sync_setup, run, pdf_bytes, NOW
from app.schemas.canvas import CanvasFile
from app.api.sync import get_sync_service


@pytest.mark.parametrize('term_id,workflow,expected', [(101,'available',None),(99,'available','different_term'),
    (None,'available','unknown_term'),(101,'completed','inactive_course')])
def test_term_identity_not_course_title(db, sync_setup, term_id, workflow, expected):
    course = CanvasCourse(id=3, name='2027 S1 Current Course', course_code='CURRENT',
                          enrollment_term_id=term_id, workflow_state=workflow)
    assert exclusion_reason(course, db.scalar(select(Semester))) == expected


def test_term_object_fallback_and_conflicting_metadata(db, sync_setup):
    semester=db.scalar(select(Semester))
    course=CanvasCourse(id=2,name='Synthetic',course_code='TEST',term={'id':101})
    assert exclusion_reason(course,semester) is None
    course.enrollment_term_id=99
    assert exclusion_reason(course,semester)=='conflicting_term_metadata'


def test_old_course_filtered_before_any_modules_download_parse_or_ai(db, sync_setup):
    service,canvas,documents,knowledge,provider,factory=sync_setup
    canvas.courses=[CanvasCourse(id=9,name='Old',course_code='OLD',enrollment_term_id=99)]
    result=run(db,sync_setup)
    assert result.details['courses_visible']==result.details['courses_excluded']==1
    assert result.details['courses_included']==0 and result.files_discovered==0
    canvas.get_modules.assert_not_called();canvas.get_module_items.assert_not_called();canvas.get_file.assert_not_called()
    assert canvas.downloads==[];documents.parse.assert_not_called();factory.assert_not_called()
    assert db.scalar(select(Resource)) is None and db.scalar(select(Course)) is None


def test_dry_run_current_only_counts_and_no_material_mutations(db,sync_setup):
    canvas=sync_setup[1]
    canvas.courses.append(CanvasCourse(id=2,name='Old',course_code='OLD',enrollment_term_id=99))
    result=run(db,sync_setup,dry_run=True)
    assert (result.details['courses_visible'],result.details['courses_included'],result.details['courses_excluded'])==(2,1,1)
    canvas.get_modules.assert_called_once_with(1001)
    assert result.files_discovered==1 and result.files_downloaded==0
    assert not canvas.downloads;sync_setup[2].parse.assert_not_called();sync_setup[5].assert_not_called()
    assert db.scalar(select(Course)) is None


def test_missing_active_mapping_fails_closed(db,sync_setup):
    semester=db.scalar(select(Semester));semester.canvas_term_id=None;db.commit()
    with pytest.raises(ValueError,match='mapping'):run(db,sync_setup)
    sync_setup[1].get_courses.assert_not_called()


def test_only_one_active_semester(db,sync_setup):
    db.add(Semester(name='Other',year=2030,term='S1',is_active=True))
    with pytest.raises(IntegrityError):db.commit()
    db.rollback()


def test_active_dashboard_default_api_and_explicit_history(client,db,graph):
    old=Semester(name='Old',year=2025,term='S1')
    db.add(Course(semester=old,code='HISTORY',name='Historical'));db.commit()
    data=client.get('/api/study/dashboard').json()
    assert data['active_semester']['id']==graph[0].id
    assert [c['code'] for c in data['courses']]==['COMPXXXX']
    assert [c['code'] for c in client.get('/api/courses').json()]==['COMPXXXX']
    assert client.get(f'/api/courses?semester_id={old.id}').json()[0]['code']=='HISTORY'


def test_stage_callbacks_record_generation_review_and_persistence(db,sync_setup):
    stages=[];service=sync_setup[0];original=service._progress
    def capture(session,record,stage,**context):
        stages.append(stage);return original(session,record,stage,**context)
    service._progress=capture
    result=run(db,sync_setup)
    assert {'checking','download','parse','generation','review','persistence'}<=set(stages)
    assert result.details['progress']['filename']=='lecture.pdf'
    assert result.details['progress']['course_code']=='COMP'
    assert result.details['progress']['module']=='Network Layer'
    assert result.details['progress']['stage']=='completed'


def test_cancel_after_current_request_no_next_request_or_resource(db,sync_setup):
    service,canvas,documents,knowledge,provider,factory=sync_setup
    canvas.metadata[202]=CanvasFile(id=202,filename='next.pdf',size=10,updated_at=NOW)
    canvas.contents[202]=pdf_bytes()
    original=provider.generate
    def generate(*args,**kwargs):
        value=original(*args,**kwargs)
        assert request_cancellation(db.scalar(select(SyncRecord.id)))
        return value
    provider.generate=generate
    result=run(db,sync_setup)
    assert result.status=='cancelled' and result.completed_at
    assert len(provider.calls)==1 and not provider.semantic_calls
    assert canvas.downloads==[201] and result.files_failed==0
    assert db.scalar(select(Resource)).sync_status=='parsed'
    # A fresh explicit request can resume later; cancellation is not sticky.
    provider.generate=original
    assert run(db,sync_setup).status=='completed'


def test_completed_resources_survive_cancellation(db,sync_setup):
    run(db,sync_setup)
    original=sync_setup[1].get_courses.side_effect
    def courses():
        assert request_cancellation(db.scalar(select(SyncRecord.id).order_by(SyncRecord.id.desc())))
        return original()
    sync_setup[1].get_courses.side_effect=courses
    assert run(db,sync_setup).status=='cancelled'
    assert db.scalar(select(Resource)).sync_status=='completed'


def test_interrupted_recovery_preserves_rows_and_counts(db):
    row=SyncRecord(files_discovered=3,files_downloaded=2,details={'usage':{'requests':7}})
    db.add(row);db.commit();recover_interrupted(db)
    assert row.status=='cancelled' and row.completed_at
    assert row.files_downloaded==2 and row.details['usage']['requests']==7


def test_background_start_returns_id_and_cancel_status_api(client,db,sync_setup):
    client.app.dependency_overrides[get_sync_service]=lambda:sync_setup[0]
    response=client.post('/api/sync?background=true',json={})
    assert response.status_code==202 and response.json()['status']=='running'
    sync_id=response.json()['id']
    # TestClient waits for BackgroundTasks before returning; actual HTTP sends 202 first.
    assert client.get(f'/api/sync/{sync_id}').json()['status']=='completed'
    assert client.get('/api/sync/current').json() is None
    assert client.post(f'/api/sync/{sync_id}/cancel').json()['status']=='completed'
    assert client.post('/api/sync/999/cancel').status_code==404


def test_poll_and_cancel_while_background_worker_is_blocked(tmp_path, sync_setup):
    from fastapi.testclient import TestClient
    from app.core.database import build_engine, init_db
    from app.main import create_app
    engine = build_engine(f'sqlite:///{(tmp_path / "concurrent.db").as_posix()}')
    init_db(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(Semester(name='Current', year=2026, term='S2', is_active=True, canvas_term_id=101))
        session.commit()
    entered, release = Event(), Event()
    original = sync_setup[1].get_modules.side_effect
    def blocked(course_id):
        entered.set()
        assert release.wait(10)
        return original(course_id)
    sync_setup[1].get_modules.side_effect = blocked
    app = create_app(engine)
    app.dependency_overrides[get_sync_service] = lambda: sync_setup[0]
    responses = []
    with TestClient(app) as client:
        worker = Thread(target=lambda: responses.append(client.post('/api/sync?background=true', json={})))
        worker.start()
        try:
            assert entered.wait(10)
            current = client.get('/api/sync/current').json()
            assert current['status'] == 'running'
            assert current['details']['progress']['course_code'] == 'COMP'
            sync_id = current['id']
            assert client.get('/health').status_code == 200
            assert client.post('/api/sync?background=true', json={}).status_code == 409
            assert client.post(f'/api/sync/{sync_id}/cancel').json()['details']['cancel_requested']
            assert client.get(f'/api/sync/{sync_id}').json()['details']['cancel_requested']
        finally:
            release.set()
            worker.join(10)
        assert not worker.is_alive() and responses[0].status_code == 202
        assert client.get(f'/api/sync/{sync_id}').json()['status'] == 'cancelled'
        assert client.get('/api/sync/current').json() is None
        assert not sync_setup[1].downloads
        sync_setup[5].assert_not_called()
    engine.dispose()


def test_upgrade_preserves_old_sync_rows_and_accepts_cancelled(engine):
    from sqlalchemy.schema import CreateTable
    from app.core.database import init_db
    SyncRecord.__table__.drop(engine)
    old_ddl = str(CreateTable(SyncRecord.__table__).compile(engine)).replace(", 'cancelled'", '')
    with engine.begin() as connection:
        connection.exec_driver_sql(old_ddl)
    factory = create_session_factory(engine)
    with factory() as session:
        row = SyncRecord(files_downloaded=7, details={'usage': {'requests': 12}})
        session.add(row); session.commit(); row_id = row.id
    init_db(engine)
    init_db(engine)
    with factory() as session:
        row = session.get(SyncRecord, row_id)
        assert row.files_downloaded == 7 and row.details['usage']['requests'] == 12
        row.status = 'cancelled'; session.commit()


def test_activate_semester_keeps_single_source_of_truth(db, graph):
    from app.configure_semester import activate
    other = Semester(name='Next semester', year=2027, term='S1')
    db.add(other); db.commit()
    activate(db, other.id, 202)
    assert not graph[0].is_active and other.is_active and other.canvas_term_id == 202
    db.add(SyncRecord()); db.commit()
    with pytest.raises(ValueError, match='running sync'):
        activate(db, graph[0].id, 101)
