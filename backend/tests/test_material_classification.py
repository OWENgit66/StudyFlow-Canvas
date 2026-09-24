from unittest.mock import Mock

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.models import DocumentChunk, Resource
from app.schemas.canvas import CanvasFile, CanvasModule, CanvasModuleItem, CanvasPage
from app.services.material_classification import MaterialClassifier, MaterialKind
from app.services.page_materials import extract_material_links
from test_sync import NOW, run, sync_setup


@pytest.mark.parametrize('title,context,expected', [
    ('Week 5 Lecture Slides.pdf', '', MaterialKind.CORE),
    ('Tutorial Week 5.pdf', '', MaterialKind.CORE),
    ('Workshop 2.pdf', '', MaterialKind.CORE),
    ('Lab exercise.pdf', '', MaterialKind.CORE),
    ('Practical.pdf', '', MaterialKind.CORE),
    ('Seminar.pdf', '', MaterialKind.CORE),
    ('Required Reading - Smith 2024.pdf', '', MaterialKind.READING),
    ('Week 5 Journal Article.pdf', '', MaterialKind.READING),
    ('Supplementary Reading.pdf', '', MaterialKind.READING),
    ('Chapter 6.pdf', 'Recommended Reading', MaterialKind.READING),
    ('Chapter 6.pdf', '', MaterialKind.UNKNOWN),
    ('Chapter 6.pdf', 'Week 6 Lecture', MaterialKind.CORE),
    ('Book Chapter 6.pdf', '', MaterialKind.READING),
    ('paper.pdf', '', MaterialKind.READING),
    ('Supplementary Material.pdf', '', MaterialKind.READING),
    ('Reference.pdf', '', MaterialKind.READING),
    ('Research Paper.pdf', '', MaterialKind.READING),
    ('Further Reading.pdf', '', MaterialKind.READING),
    ('Additional Reading.pdf', '', MaterialKind.READING),
    ('Optional Reading.pdf', '', MaterialKind.READING),
    ('a83f901.pdf', '', MaterialKind.UNKNOWN),
    ('Notes.pdf', 'Week 5', MaterialKind.UNKNOWN),
    ('Collaboration.pdf', '', MaterialKind.UNKNOWN),
    ('Week_5_LECTURE-SLIDES.PDF', '', MaterialKind.CORE),
    ('Journal Articles.pdf', '', MaterialKind.READING),
    ('Lecture reading.pdf', '', MaterialKind.READING),
    ('article.docx', '', MaterialKind.READING),
])
def test_title_policy(title, context, expected):
    classifier = MaterialClassifier(Settings(_env_file=None))
    assert classifier.classify(filename=title, page_title=context).kind == expected


def test_literal_terms_configurable_from_environment(monkeypatch):
    monkeypatch.setenv('MATERIAL_CORE_TERMS', 'studio|worked examples')
    monkeypatch.setenv('MATERIAL_READING_TERMS', 'bibliography|reading list')
    monkeypatch.setenv('MATERIAL_IGNORE_READINGS', 'false')
    settings = Settings(_env_file=None)
    classifier = MaterialClassifier(settings)
    assert not settings.material_ignore_readings
    assert classifier.classify(filename='Studio.pdf').kind == MaterialKind.CORE
    assert classifier.classify(filename='Bibliography.pdf').kind == MaterialKind.READING
    assert classifier.classify(filename='Lecture.pdf').kind == MaterialKind.UNKNOWN


def test_html_context_tracks_headings_paragraphs_and_link_text_without_script_content():
    links, _ = extract_material_links('''
        <h2>Lecture</h2><p><a href="/files/1"><b>Week 5</b> Slides</a></p>
        <h2>Required Reading</h2><p><a href="/files/2">Chapter 6</a></p>
        <h2>Workshop</h2><p><a href="/files/3">Handout</a></p>
        <h2>Week 5</h2><p>Recommended Reading: <a href="/files/4">Smith</a> 2024</p>
        <p><a href="/files/5">Other</a><script>Required Reading</script></p>
    ''', 'https://canvas.example.test', 1, 'week')
    classifier = MaterialClassifier(Settings(_env_file=None))
    kinds = [classifier.classify(link_text=l.link_text, nearby_text=l.surrounding_text).kind for l in links]
    assert kinds == [MaterialKind.CORE, MaterialKind.READING, MaterialKind.CORE,
                     MaterialKind.READING, MaterialKind.UNKNOWN]
    assert 'Chapter 6' in links[1].link_text
    assert 'Recommended Reading' in links[3].surrounding_text


def test_plain_paragraph_reading_labels_before_lists_and_links_do_not_leak_to_next_section():
    links, _ = extract_material_links('''
        <h2>Before lecture</h2><p>Essential reading. Read this before the lecture:</p>
        <ul><li>Example author <a href="/files/1">Chapter 6</a></li></ul>
        <p>Recommended readings. If you have time:</p>
        <ul><li><a href="/files/2">Background</a></li><li><a href="/files/3">More background</a></li></ul>
        <h2>Lecture materials</h2><p><a href="/files/4">Slides</a></p>
        <h2>Other</h2><p>Optional Reading:</p><p><a href="/files/5">Notes</a></p>
        <p><a href="/files/6">Other attachment</a></p>
    ''', 'https://canvas.example.test', 1, 'week')
    classifier = MaterialClassifier(Settings(_env_file=None))
    assert [classifier.classify(link_text=l.link_text, nearby_text=l.surrounding_text).kind for l in links] == [
        MaterialKind.READING, MaterialKind.READING, MaterialKind.READING,
        MaterialKind.CORE, MaterialKind.READING, MaterialKind.UNKNOWN]


def assert_ignored(db, setup, result, count=1):
    assert result.status == 'completed' and result.files_failed == 0
    assert result.details['ignored_reading_materials'] == count
    assert result.files_skipped == count and result.files_downloaded == 0
    assert result.details['files_parsed'] == result.details['files_analyzed'] == 0
    assert not setup[1].downloads
    setup[2].parse.assert_not_called()
    setup[5].assert_not_called()
    assert db.scalar(select(func.count()).select_from(Resource)) == 0
    assert db.scalar(select(func.count()).select_from(DocumentChunk)) == 0
    assert result.details['events'][0]['outcome'] == 'ignored_reading_material'
    assert not result.details['errors']


@pytest.mark.parametrize('dry_run', [False, True])
def test_direct_reading_item_skips_before_metadata_even_if_inaccessible(db, sync_setup, dry_run):
    canvas = sync_setup[1]
    canvas.get_module_items = Mock(return_value=[CanvasModuleItem(
        id=1, module_id=51, title='Required Reading - Smith 2024.pdf', type='File', content_id=201)])
    canvas.get_file = Mock(side_effect=AssertionError('Reading metadata should not be requested'))
    result = run(db, sync_setup, dry_run=dry_run)
    assert_ignored(db, sync_setup, result)
    canvas.get_file.assert_not_called()


@pytest.mark.parametrize('field', ['filename', 'display_name'])
def test_metadata_reading_classification_before_timestamp_or_lock_validation(db, sync_setup, field):
    canvas = sync_setup[1]
    canvas.get_module_items = Mock(return_value=[CanvasModuleItem(
        id=1, module_id=51, title='Download', type='File', content_id=201)])
    canvas.metadata[201] = CanvasFile(id=201, filename='opaque.pdf', size=10, locked_for_user=True)
    setattr(canvas.metadata[201], field, 'Journal Article.pdf')
    assert_ignored(db, sync_setup, run(db, sync_setup))


@pytest.mark.parametrize('source', ['page', 'module', 'link', 'heading', 'paragraph'])
def test_page_reading_context_skips_all_processing(db, sync_setup, source):
    canvas = sync_setup[1]
    sync_setup[0].settings.canvas_base_url = 'https://canvas.example.test'
    if source == 'module':
        canvas.modules = [CanvasModule(id=51, name='Required Reading', position=1)]
    title = 'Required Reading' if source == 'page' else 'Week 5'
    anchor = '<a href="/files/201">' + ('Optional Reading' if source == 'link' else 'Chapter 6') + '</a>'
    body = ('<h2>Required Reading</h2>' if source == 'heading' else '') + '<p>' + (
        'Supplementary Material: ' if source == 'paragraph' else '') + anchor + '</p>'
    canvas.get_module_items = Mock(return_value=[CanvasModuleItem(
        id=1, module_id=51, title='Week 5', type='Page', page_url='week')])
    canvas.get_page = Mock(return_value=CanvasPage(page_id=1, url='week', title=title, body=body))
    assert_ignored(db, sync_setup, run(db, sync_setup))
    canvas.get_file.assert_not_called()


@pytest.mark.parametrize('reverse', [False, True])
def test_duplicate_reading_evidence_wins_independent_of_item_order(db, sync_setup, reverse):
    canvas = sync_setup[1]
    sync_setup[0].settings.canvas_base_url = 'https://canvas.example.test'
    items = [CanvasModuleItem(id=1, module_id=51, title='Lecture', type='File', content_id=201),
             CanvasModuleItem(id=2, module_id=51, title='Week', type='Page', page_url='week')]
    canvas.get_module_items = Mock(return_value=items[::-1] if reverse else items)
    canvas.get_page = Mock(return_value=CanvasPage(page_id=1, url='week', title='Week',
        body='<a href="/files/201">Required Reading</a><a href="/files/201">Required Reading</a>'))
    result = run(db, sync_setup)
    assert_ignored(db, sync_setup, result)
    assert result.files_discovered == result.details['reading_materials_discovered'] == 1


def test_mixed_core_reading_unknown_page_dry_run_reports_each_without_processing(db, sync_setup):
    canvas = sync_setup[1]
    sync_setup[0].settings.canvas_base_url = 'https://canvas.example.test'
    canvas.get_module_items = Mock(return_value=[CanvasModuleItem(
        id=1, module_id=51, title='Week 5', type='Page', page_url='week')])
    canvas.get_page = Mock(return_value=CanvasPage(page_id=1, url='week', title='Week 5', body='''
        <h2>Lecture</h2><p><a href="/files/201">Slides</a></p>
        <h2>Required Reading</h2><p><a href="/files/202">Chapter 6</a></p>
        <h2>Other</h2><p><a href="/files/203">Attachment</a></p>'''))
    canvas.metadata[203] = CanvasFile(id=203, filename='opaque.pdf', size=10, updated_at=NOW)
    result = run(db, sync_setup, dry_run=True)
    assert result.status == 'completed'
    assert result.details['core_materials_discovered'] == 1
    assert result.details['ignored_reading_materials'] == 1
    assert result.details['unknown_materials'] == 1
    assert [e['material_classification'] for e in result.details['events']] == [
        'CORE_MATERIAL', 'READING_MATERIAL', 'UNKNOWN']
    assert result.files_discovered == 3 and result.files_failed == 0
    assert result.files_downloaded == 0
    sync_setup[2].parse.assert_not_called()
    sync_setup[5].assert_not_called()
    assert db.scalar(select(func.count()).select_from(Resource)) == 0


def test_unknown_preserves_existing_processing_behavior(db, sync_setup):
    canvas = sync_setup[1]
    canvas.metadata[201].filename = 'a83f901.pdf'
    result = run(db, sync_setup)
    assert result.status == 'completed' and result.files_downloaded == 1
    assert result.details['unknown_materials'] == 1
    assert result.details['files_analyzed'] == 1


def test_external_reading_skips_before_head_request(db, sync_setup):
    canvas = sync_setup[1]
    sync_setup[0].settings.canvas_base_url = 'https://canvas.example.test'
    canvas.get_module_items = Mock(return_value=[CanvasModuleItem(
        id=1, module_id=51, title='Week 5', type='Page', page_url='week')])
    canvas.get_page = Mock(return_value=CanvasPage(page_id=1, url='week', title='Week',
        body='<a href="https://public.example.test/Required%20Reading.pdf">Download</a>'))
    canvas.get_external_file = Mock(side_effect=AssertionError('Should not access ignored external PDF'))
    assert_ignored(db, sync_setup, run(db, sync_setup))
    canvas.get_external_file.assert_not_called()


def test_existing_reading_resources_and_chunks_are_preserved(db, sync_setup):
    run(db, sync_setup)
    resource = db.scalar(select(Resource))
    chunk = db.scalar(select(DocumentChunk))
    before = (resource.sync_status, resource.local_path, resource.canvas_updated_at, chunk.id, chunk.content)
    canvas = sync_setup[1]
    canvas.get_module_items = Mock(return_value=[CanvasModuleItem(
        id=1, module_id=51, title='Required Reading', type='File', content_id=201)])
    counts = (len(canvas.downloads), sync_setup[2].parse.call_count, sync_setup[5].call_count)
    result = run(db, sync_setup)
    assert result.details['ignored_reading_materials'] == 1 and result.files_failed == 0
    assert counts == (len(canvas.downloads), sync_setup[2].parse.call_count, sync_setup[5].call_count)
    db.refresh(resource); db.refresh(chunk)
    assert before == (resource.sync_status, resource.local_path, resource.canvas_updated_at, chunk.id, chunk.content)


def test_explicit_setting_can_opt_in_to_reading_processing(db, sync_setup):
    sync_setup[0].settings.material_ignore_readings = False
    sync_setup[1].metadata[201].filename = 'Required Reading.pdf'
    result = run(db, sync_setup)
    assert result.status == 'completed' and result.files_downloaded == 1
    assert result.details['reading_materials_discovered'] == 1
    assert result.details['ignored_reading_materials'] == 0
