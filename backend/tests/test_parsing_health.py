from copy import deepcopy
from unittest.mock import Mock

import pymupdf
import pytest
from sqlalchemy import select

from app.api.study import get_material_root
from app.core.config import Settings
from app.models import Course, Resource, Semester, Week, DocumentChunk
from app.schemas.document import ParsedDocument, ParsedPage, ParsingWarning
from app.services.document_service import DocumentService
from app.services.document_processing import process_resource
from app.services.parsing_health import build_report, read_health, source_fingerprint, store_report
from app.refresh_parsing_health import refresh
from test_sync import sync_setup, run


def pdf(path, *, warnings=False):
    with pymupdf.open() as document:
        document.new_page().insert_text((50, 100), 'A readable introduction.')
        if warnings:
            page = document.new_page()
            page.insert_text((50, 100), '2', fontsize=20)
            page.insert_text((61, 94), 'N-1', fontsize=12)
            document.new_page()
        document.save(path)


@pytest.fixture
def parsed(db, graph, tmp_path, client):
    path = tmp_path / 'lecture.pdf'
    pdf(path, warnings=True)
    resource = graph[-1]; resource.local_path = str(path); db.commit()
    documents = DocumentService(Settings(_env_file=None, materials_root=tmp_path))
    process_resource(db, resource.id, documents)
    client.app.dependency_overrides[get_material_root] = lambda: tmp_path
    return resource, path, documents


def test_report_exact_pages_safe_response_and_course_counts(db, client, graph, parsed, monkeypatch):
    resource, path, documents = parsed
    health = read_health(resource, documents.root)
    assert health.total_pages == 3 and health.pages_with_text == 2
    assert health.pages_need_review == 2
    assert {(i.page_number, i.category) for i in health.issues} >= {
        (2, 'suspicious_formula_layout'), (3, 'empty_text'), (3, 'possible_scanned_page')}
    monkeypatch.setattr(DocumentService, 'parse', Mock(side_effect=AssertionError('GET must never parse')))
    response = client.get(f'/api/weeks/{resource.week_id}/resources')
    assert response.status_code == 200
    assert response.json()[0]['parsing_health']['pages_need_review'] == 2
    assert all(secret not in response.text for secret in ['bbox', 'span_indices', 'font', 'fingerprint', str(path), 'raw_text'])
    week = client.get(f'/api/courses/{graph[1].id}/weeks').json()[0]
    assert week['resources_need_review'] == 1 and week['resource_count'] == 1
    assert client.get(f'/api/weeks/{resource.week_id}').json()['resources_need_review'] == 1
    assert resource.sync_status == 'parsed'


def test_read_healthy_unknown_unavailable_and_non_pdf(db, graph, tmp_path):
    resource = graph[-1]; path = tmp_path/'clean.pdf'; pdf(path)
    resource.local_path = str(path); db.commit()
    assert read_health(resource, tmp_path).status == 'unknown'
    process_resource(db, resource.id, DocumentService(Settings(_env_file=None, materials_root=tmp_path)))
    report = read_health(resource, tmp_path)
    assert report.status == 'healthy' and report.pages_need_review == 0
    resource.local_path = str(tmp_path/'absent.pdf')
    assert read_health(resource, tmp_path).status == 'unavailable'
    resource.file_type = 'docx'
    assert read_health(resource, tmp_path).status == 'unsupported'


def test_changed_pdf_or_wrong_resource_never_receives_historical_warnings(db, parsed):
    resource, path, documents = parsed
    stored = deepcopy(resource.parsing_report)
    resource.parsing_report = {**stored, 'resource_id': resource.id+1}
    assert read_health(resource, documents.root).status == 'stale'
    resource.parsing_report = stored
    path.write_bytes(path.read_bytes()+b'\n% source changed')
    health = read_health(resource, documents.root)
    assert health.status == 'stale' and health.issues == [] and health.total_pages is None


def test_existing_symbolic_detectors_and_labels_are_reused():
    page = ParsedPage(page_number=18, raw_text='A \ue001 B \ufffd', text='A = ... = B', warnings=[
        ParsingWarning(code='encoding_warning', message='PRIVATE INTERNAL', span_indices=[4])])
    report = build_report(ParsedDocument(resource_id=12, filename='test.pdf', pages=[page]))
    assert report.pages_need_review == 1
    assert {i.category for i in report.issues} == {'encoding_warning','unreadable_symbol','suspicious_symbolic_expression'}
    assert all(i.page_number == 18 and i.label != i.category for i in report.issues)
    assert 'PRIVATE' not in report.model_dump_json() and 'span_indices' not in report.model_dump_json()


def test_repeated_margin_cleanup_is_info_not_a_review_problem():
    page = ParsedPage(page_number=1, raw_text='Lecture\nKnowledge', text='Knowledge', warnings=[
        ParsingWarning(code='repeated_header_footer', message='Removed footer')])
    report = build_report(ParsedDocument(resource_id=1, filename='a.pdf', pages=[page]))
    assert report.status == 'healthy' and report.pages_need_review == 0
    assert report.issues[0].severity == 'info'


def test_invalid_pdf_stores_safe_failure_report(db, graph, tmp_path):
    from app.services.document_errors import DocumentError
    resource = graph[-1]; path = tmp_path/'bad.pdf'; path.write_bytes(b'PRIVATE invalid data')
    resource.local_path = str(path); db.commit()
    with pytest.raises(DocumentError):
        process_resource(db, resource.id, DocumentService(Settings(_env_file=None, materials_root=tmp_path)))
    report = read_health(resource, tmp_path)
    assert report.status == 'unable_to_parse' and 'PRIVATE' not in report.model_dump_json()


def test_backfill_only_current_semester_preserves_chunks_and_status(db, graph, tmp_path):
    resource = graph[-1]; path = tmp_path/'current.pdf'; pdf(path)
    resource.local_path = str(path); resource.sync_status = 'completed'
    chunk = DocumentChunk(resource=resource, page_number=1, chunk_index=0, content='Original persisted chunk')
    old = Resource(week=Week(course=Course(semester=Semester(name='Old',year=2025,term='S2'),code='OLD',name='Old'),
        week_number=1,title='Old'), filename='old.pdf', file_type='pdf', local_path=str(path))
    db.add_all([chunk,old]); db.commit()
    documents = DocumentService(Settings(_env_file=None, materials_root=tmp_path))
    documents.parse = Mock(wraps=documents.parse)
    counts = refresh(db, documents)
    assert counts['reviewed'] == counts['healthy'] == 1
    assert documents.parse.call_count == 1 and old.parsing_report is None
    assert resource.sync_status == 'completed'
    assert db.scalar(select(DocumentChunk.content)) == 'Original persisted chunk'


def test_sync_warning_is_telemetry_not_failure(db, sync_setup, tmp_path):
    path = tmp_path/'with-warning.pdf'; pdf(path, warnings=True)
    sync_setup[1].contents[201] = path.read_bytes()
    result = run(db, sync_setup)
    assert result.files_failed == 0 and result.status == 'completed'
    assert result.details['progress']['parsing_review_pages'] == 2
