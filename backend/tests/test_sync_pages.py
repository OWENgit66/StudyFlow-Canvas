from datetime import timedelta
from unittest.mock import Mock
from sqlalchemy import select, func

from app.models import Resource, Course, Week
from app.schemas.canvas import CanvasPage, CanvasModuleItem, CanvasFile, CanvasCourse, CanvasModule
from app.schemas.sync import SyncRequest
from app.services.canvas_errors import CanvasPermissionError
from app.services.external_pdf import ExternalPDF, ExternalPDFError
from app.services.page_materials import external_key
from test_sync import sync_setup, run, pdf_bytes, NOW
from app.services.canvas_storage import save_stream
from app.services.material_paths import build_material_path


def pages(setup, bodies):
    service, canvas = setup[:2]
    service.settings.canvas_base_url = 'https://canvas.example.test'
    canvas.get_module_items = Mock(side_effect=lambda c,m: [CanvasModuleItem(id=i, module_id=m,
        title=f'Page {i}', type='Page', page_url=f'page-{i}') for i in bodies])
    canvas.get_page = Mock(side_effect=lambda c,p: CanvasPage(page_id=int(p[5:]),url=p,title=p,body=bodies[int(p[5:])]))
    return canvas


def test_page_inspected_multiple_files_resolved_and_module_ownership(db, sync_setup):
    canvas = pages(sync_setup, {1:'<a href="/courses/1001/files/201/download">A</a><a href="/files/202">B</a>'})
    canvas.metadata[202] = CanvasFile(id=202,filename='other.pdf',size=10,updated_at=NOW)
    canvas.contents[202] = pdf_bytes()
    result = run(db, sync_setup)
    assert result.status == 'completed' and result.files_downloaded == 2
    assert (result.details['pages_inspected'],result.details['page_links_found'],result.details['page_files_resolved']) == (1,2,2)
    assert result.details['page_linked_files_discovered'] == 2
    for resource in db.scalars(select(Resource)):
        assert resource.week.canvas_module_id == 51 and resource.week.course.canvas_course_id == 1001
        assert 'Network Layer' in resource.local_path and resource.external_source_key is None
    canvas.get_page.assert_called_once_with(1001,'page-1')


def test_page_and_direct_file_and_multiple_pages_modules_deduplicate(db, sync_setup):
    canvas = pages(sync_setup, {1:'<a href="/files/201">A</a>',2:'<a href="/files/201/download">A</a>'})
    original = canvas.get_module_items.side_effect
    canvas.get_module_items.side_effect = lambda c,m: [CanvasModuleItem(id=9,module_id=m,title='Direct',type='File',content_id=201),*original(c,m)]
    canvas.modules.append(CanvasModule(id=52,name='Second module',position=2))
    result = run(db,sync_setup)
    assert result.files_discovered == result.files_downloaded == result.details['page_files_resolved'] == 1
    assert result.details['pages_inspected'] == 4 and result.details['page_links_found'] == 4
    assert result.details['page_linked_files_discovered'] == 1
    assert db.scalar(select(func.count()).select_from(Resource)) == 1
    assert db.scalar(select(Resource)).week.canvas_module_id == 51


def test_page_changes_do_not_reprocess_unchanged_file_but_file_updates_do(db, sync_setup):
    bodies={1:'<a href="/files/201">A</a>'}
    canvas=pages(sync_setup,bodies)
    run(db,sync_setup)
    before=(len(canvas.downloads),sync_setup[2].parse.call_count,sync_setup[5].call_count)
    bodies[1]='<p>Changed page text</p><a href="/files/201">Renamed link</a>'
    result=run(db,sync_setup)
    assert result.files_skipped==1 and result.files_downloaded==0
    assert before==(len(canvas.downloads),sync_setup[2].parse.call_count,sync_setup[5].call_count)
    canvas.metadata[201].updated_at+=timedelta(days=1)
    updated=run(db,sync_setup)
    assert updated.files_updated==updated.details['files_analyzed']==1
    assert db.scalar(select(func.count()).select_from(Resource))==1


def test_non_pdf_internal_and_unsupported_external_links_safe(db,sync_setup):
    canvas=pages(sync_setup,{1:'<a href="/files/201">Slides</a><a href="https://drive.google.com/file/d/x/view">Drive</a><a href="/assignments/1">Assignment</a>'})
    canvas.metadata[201].filename='slides.pptx'
    result=run(db,sync_setup)
    assert result.status=='completed' and result.details['page_links_unsupported']==2
    assert result.files_downloaded==1 and db.scalar(select(Resource)).sync_stage=='unsupported'
    sync_setup[2].parse.assert_not_called();sync_setup[5].assert_not_called()


def test_page_failure_isolated_and_safe(db,sync_setup):
    canvas=pages(sync_setup,{1:'',2:'<a href="/files/201">A</a>'})
    original=canvas.get_page.side_effect
    canvas.get_page.side_effect=lambda c,p: (_ for _ in ()).throw(CanvasPermissionError('PRIVATE_BODY')) if p=='page-1' else original(c,p)
    result=run(db,sync_setup)
    assert result.status=='completed_with_errors' and result.files_downloaded==1
    assert result.details['pages_inspected']==2 and result.details['errors'][0]['stage']=='page'
    assert 'PRIVATE_BODY' not in result.model_dump_json()


def test_semester_filter_and_dry_run_prevent_unscoped_processing(db,sync_setup):
    canvas=pages(sync_setup,{1:'<a href="/files/201">A</a>'})
    canvas.courses.append(CanvasCourse(id=999,name='Old',course_code='OLD',enrollment_term_id=99))
    result=run(db,sync_setup,dry_run=True)
    canvas.get_modules.assert_called_once_with(1001)
    canvas.get_page.assert_called_once_with(1001,'page-1')
    assert result.details['events'][0]['outcome']=='NEW'
    assert result.files_downloaded==0 and not canvas.downloads
    assert db.scalar(select(Course)) is None and db.scalar(select(Resource)) is None
    sync_setup[2].parse.assert_not_called();sync_setup[5].assert_not_called()


def test_file_scope_matches_page_file(db,sync_setup):
    canvas=pages(sync_setup,{1:'<a href="/files/201">A</a>'})
    run(db,sync_setup)
    course=db.scalar(select(Course))
    result=sync_setup[0].run(db,SyncRequest(course_id=course.id,module_id=51,file_id=201),dry_run=True)
    assert result.files_discovered==result.files_skipped==1


def test_unresolved_canvas_file_does_not_block_other_files(db,sync_setup):
    pages(sync_setup,{1:'<a href="/files/999">Broken</a><a href="/files/201">Good</a>'})
    result=run(db,sync_setup)
    assert result.files_failed==1 and result.files_downloaded==1
    assert result.details['page_links_unresolved']==1


def test_external_pdf_uses_separate_identity_existing_storage_and_incremental_path(db,sync_setup):
    url='https://public.example.test/notes.pdf'
    canvas=pages(sync_setup,{1:f'<a href="{url}">A</a><a href="{url}#page=3">Again</a>'})
    content=pdf_bytes()
    remote=ExternalPDF(external_key(url),'revision-1','notes.pdf',len(content),url)
    canvas.get_external_file=Mock(return_value=remote)
    def download(meta,*,context,existing_path=None):
        return save_stream(canvas.root,build_material_path(canvas.root,context,meta.filename),[content],len(content),1000000,existing_path=existing_path)
    canvas.download_external_file=Mock(side_effect=download)
    first=run(db,sync_setup)
    assert first.files_discovered==first.files_downloaded==1
    resource=db.scalar(select(Resource))
    assert resource.canvas_file_id is None and resource.external_source_key==external_key(url)
    assert 'Network Layer' in resource.local_path
    assert run(db,sync_setup).files_skipped==1
    assert canvas.download_external_file.call_count==1
    canvas.get_external_file.return_value=ExternalPDF(remote.source_key,'revision-2',remote.filename,remote.size,url)
    assert run(db,sync_setup).files_updated==1
    assert db.scalar(select(func.count()).select_from(Resource))==1


def test_unsafe_external_metadata_reported_without_download(db,sync_setup):
    canvas=pages(sync_setup,{1:'<a href="https://127.0.0.1/a.pdf">Unsafe</a><a href="/files/201">Good</a>'})
    canvas.get_external_file=Mock(side_effect=ExternalPDFError('PRIVATE_URL'))
    result=run(db,sync_setup,dry_run=True)
    assert result.files_failed==result.details['page_links_unsupported']==1
    assert result.details['files_checked']==1 and not canvas.downloads
    assert 'PRIVATE_URL' not in result.model_dump_json()
