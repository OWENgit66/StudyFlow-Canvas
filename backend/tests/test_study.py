from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.api.study import get_material_root
from app.models import Resource, SyncRecord, Week
from app.models.common import ResourceStatus, SyncStatus


def test_dashboard_empty(client):
    assert client.get('/api/study/dashboard').json() == {
        'semesters': [], 'courses': [], 'latest_sync': None, 'active_semester': None}


def test_dashboard_real_counts_titles_and_safe_sync(client, db, graph):
    semester, course, week, resource = graph
    resource.sync_status = ResourceStatus.parsed
    revision = Week(course=course, week_number=3, title='Revision', canvas_module_id=456)
    db.add(revision)
    db.add(SyncRecord(status=SyncStatus.failed, error_message='private path and credentials',
                      details={'private': 'should not reach dashboard'}))
    db.commit()
    result = client.get('/api/study/dashboard')
    assert result.status_code == 200
    data = result.json()
    assert data['semesters'][0]['id'] == semester.id
    card = data['courses'][0]
    assert card['id'] == course.id
    assert card['module_count'] == 2 and card['parsed_resource_count'] == 1
    assert card['latest_module'] == 'Revision'
    assert 'private' not in result.text and 'error_message' not in data['latest_sync']
    assert client.get(f'/api/weeks/{revision.id}').json()['canvas_module_id'] == 456


@pytest.fixture
def material(client, db, graph, tmp_path):
    root = tmp_path / 'materials'
    root.mkdir()
    path = root / 'lecture.pdf'
    path.write_bytes(b'%PDF-1.7\ncourse-file')
    resource = graph[-1]
    resource.local_path = str(path)
    db.commit()
    client.app.dependency_overrides[get_material_root] = lambda: root
    return resource, path, root


def test_resources_list_has_no_paths_or_knowledge_claim(client, db, material):
    resource, path, root = material
    data = client.get(f'/api/weeks/{resource.week_id}/resources').json()[0]
    assert data['filename'] == resource.filename
    assert data['size_bytes'] == path.stat().st_size
    assert data['file_available'] is True
    assert 'local_path' not in data and str(root) not in str(data)
    # The presentation query never changes pipeline state or fabricates knowledge.
    assert db.get(Resource, resource.id).sync_status == ResourceStatus.pending
    assert db.scalar(select(func.count()).select_from(Resource)) == 1


def test_registered_pdf_opens_and_downloads_with_range_support(client, material):
    resource, path, _ = material
    response = client.get(f'/api/resources/{resource.id}/file')
    assert response.status_code == 200 and response.content == path.read_bytes()
    assert response.headers['content-type'] == 'application/pdf'
    assert response.headers['content-disposition'].startswith('inline;')
    assert resource.filename in response.headers['content-disposition']
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['cache-control'] == 'no-store'
    response = client.get(f'/api/resources/{resource.id}/file?download=true')
    assert response.headers['content-disposition'].startswith('attachment;')
    partial = client.get(f'/api/resources/{resource.id}/file', headers={'Range': 'bytes=0-4'})
    assert partial.status_code == 206 and partial.content == b'%PDF-'


@pytest.mark.parametrize('mode', ['outside', 'traversal', 'missing', 'directory'])
def test_unavailable_or_escaping_registered_path_is_hidden(client, db, material, mode):
    resource, path, root = material
    outside = root.parent / 'private.pdf'
    outside.write_bytes(b'private contents')
    resource.local_path = {'outside': str(outside), 'traversal': str(root / '..' / 'private.pdf'),
                           'missing': str(root / 'missing.pdf'), 'directory': str(root)}[mode]
    db.commit()
    response = client.get(f'/api/resources/{resource.id}/file')
    assert response.status_code == 404
    assert str(root) not in response.text and 'private contents' not in response.text
    row = client.get(f'/api/weeks/{resource.week_id}/resources').json()[0]
    assert row['file_available'] is False and row['size_bytes'] is None


def test_non_pdf_cannot_execute_inline(client, db, material):
    resource, path, _ = material
    html = path.with_suffix('.html')
    html.write_text('<script>should not run</script>')
    resource.filename, resource.file_type, resource.local_path = 'lecture.html', 'html', str(html)
    db.commit()
    response = client.get(f'/api/resources/{resource.id}/file')
    assert response.headers['content-type'] == 'application/octet-stream'
    assert response.headers['content-disposition'].startswith('attachment;')


def test_unknown_resource_and_module(client):
    assert client.get('/api/resources/9999/file').status_code == 404
    assert client.get('/api/weeks/9999/resources').status_code == 404
    assert client.get('/api/resources/0/file').status_code == 422


def test_symlink_escape_is_hidden_without_host_symlink_privilege(client, db, material, monkeypatch):
    resource, _, root = material
    # Simulate resolve() following a registered symlink out of MATERIALS_ROOT.
    outside = root.parent / 'private.pdf'
    outside.write_bytes(b'private')
    monkeypatch.setattr('app.api.study.resolve_database_path', lambda _: outside.resolve())
    assert client.get(f'/api/resources/{resource.id}/file').status_code == 404


def test_no_resources_for_existing_week(client, db, graph):
    week = Week(course=graph[1], week_number=4, title='Assessment resources')
    db.add(week); db.commit()
    assert client.get(f'/api/weeks/{week.id}/resources').json() == []
