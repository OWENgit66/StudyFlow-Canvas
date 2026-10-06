"""Synthetic role evidence only. Never requires course files or live providers."""
import json
from unittest.mock import Mock

import pytest
from sqlalchemy import select, text, update

from app.models import DocumentChunk, Resource
from app.models.common import ResourceType
from app.services.ai_errors import AITransientError
from app.services.material_classification import score_resource_metadata
from app.services.resource_classification import ResourceClassificationService, early_text
from test_sync import run, sync_setup


@pytest.mark.parametrize('metadata,role,high', [
    ({'filename': 'Week 5 Lecture.pdf'}, 'lecture', True),
    ({'filename': 'Tutorial Solutions.pdf'}, 'tutorial', True),
    ({'filename': 'Assignment1.pdf', 'module_title': 'Lectures'}, 'other', True),
    ({'filename': 'Required Reading.pdf', 'module_title': 'Lecture'}, 'other', True),
    ({'filename': 'Syllabus.pdf'}, 'other', True),
    ({'filename': 'Week 5 Lecture.pdf', 'nearby_text': 'Recommended reading'}, 'lecture', True),
    ({'filename': 'Worksheet.pdf', 'page_title': 'Lecture'}, 'lecture', True),
    ({'filename': 'Notes.pdf', 'module_title': 'Lectures'}, 'lecture', False),
    ({'filename': 'Slides.pdf'}, 'other', False),
    ({'filename': 'Lecture and Tutorial.pdf'}, 'other', False),
    ({'filename': 'Network Layer.pdf'}, 'other', False),
    ({'filename': 'Machine Learning.pdf'}, 'other', False),
])
def test_metadata_scores(metadata, role, high):
    result = score_resource_metadata(**metadata)
    assert result.resource_type == role
    assert (result.confidence >= 0.8) == high
    assert 0 <= result.confidence <= 1


def opening(db, resource, content):
    for chunk in db.scalars(select(DocumentChunk).where(DocumentChunk.resource_id == resource.id)):
        db.delete(chunk)
    db.flush()
    db.add(DocumentChunk(resource_id=resource.id, page_number=1, chunk_index=0, content=content))
    db.commit()


@pytest.mark.parametrize('content,expected', [('Week 5 Lecture\nIntroduction', 'lecture'),
    ('Tutorial\nExercises\nSolve these problems', 'tutorial'), ('Assignment\nRubric', 'other')])
def test_content_fallback(db, graph, content, expected):
    resource = graph[-1]
    opening(db, resource, content)
    provider = Mock()
    result = ResourceClassificationService(provider, max_llm_calls=1).apply(
        db, resource, metadata={'filename': 'Notes.pdf', 'module_title': 'Week 5'})
    db.commit(); db.refresh(resource)
    assert result.resource_type == expected and result.method == 'document_content'
    assert resource.classification_method == 'document_content'
    assert resource.classification_confidence == 0.85
    provider.generate.assert_not_called()


def test_high_metadata_never_reads_content_or_calls_provider(db, graph, monkeypatch):
    load = Mock(side_effect=AssertionError('Should not read chunks'))
    monkeypatch.setattr('app.services.resource_classification.early_text', load)
    provider = Mock()
    result = ResourceClassificationService(provider, max_llm_calls=1).classify(
        db, graph[-1], metadata={'filename': 'Tutorial.pdf'})
    assert result.resource_type == 'tutorial'
    load.assert_not_called(); provider.generate.assert_not_called()


def test_absent_text_no_provider_is_safe(db, graph):
    resource = graph[-1]
    opening(db, resource, '')
    result = ResourceClassificationService().classify(db, resource, metadata={'filename': 'Topic.pptx'})
    assert result.resource_type == 'other' and result.confidence < 0.8


def test_generic_overview_alone_is_not_high_confidence():
    from app.services.resource_classification import score_content
    assert score_content('Overview\nAn unknown document').confidence < 0.8
    assert score_content('Overview\nLearning Objectives').resource_type == 'lecture'


def test_incomplete_download_does_not_classify_from_old_chunks(db, graph, monkeypatch):
    resource = graph[-1]
    resource.sync_stage = 'parse'; db.commit()
    monkeypatch.setattr('app.services.resource_classification.early_text', Mock(side_effect=AssertionError()))
    result = ResourceClassificationService().classify(db, resource, metadata={'filename':'Unknown.pdf'})
    assert result.resource_type == 'other'


def test_llm_fallback_budget_and_persistence(db, graph):
    resource = graph[-1]
    opening(db, resource, 'An ambiguous document opening.')
    provider = Mock()
    provider.generate.return_value = json.dumps({'resource_type': 'lecture', 'confidence': 0.86,
                                                'reason': 'Opening text explains concepts.'})
    service = ResourceClassificationService(provider, max_llm_calls=1)
    before = (resource.updated_at, resource.local_path, resource.sync_status)
    result = service.apply(db, resource, metadata={'filename': 'Notes.pdf'})
    db.commit(); db.refresh(resource)
    assert result.method == 'llm' and resource.resource_type == 'lecture'
    assert resource.classification_source == 'automatic' and resource.classification_confidence == 0.86
    assert before == (resource.updated_at, resource.local_path, resource.sync_status)
    assert provider.generate.call_count == service.llm_calls == 1
    system, payload, schema = provider.generate.call_args.args
    assert 'JSON' in system and 'untrusted' in system
    assert json.loads(payload)['opening_text'] == 'An ambiguous document opening.'
    assert schema['additionalProperties'] is False
    service.classify(db, resource)
    assert provider.generate.call_count == 1  # exhausted, no automatic retries


@pytest.mark.parametrize('output', ['', '{', '{}',
    '{"resource_type":"lab","confidence":0.9,"reason":"x"}',
    '{"resource_type":"lecture","confidence":2,"reason":"x"}',
    '{"resource_type":"lecture","confidence":"0.9","reason":"x"}',
    '{"resource_type":"lecture","confidence":true,"reason":"x"}',
    '{"resource_type":"lecture","confidence":0.9,"reason":"x","extra":1}',
    '{"resource_type":"lecture","confidence":0.4,"reason":"uncertain"}'])
def test_bad_or_uncertain_llm_keeps_safe_other(db, graph, output):
    opening(db, graph[-1], '')
    provider = Mock(); provider.generate.return_value = output
    result = ResourceClassificationService(provider, max_llm_calls=1).classify(
        db, graph[-1], metadata={'filename': 'Notes.pdf', 'module_title': 'Week 1'})
    assert result.resource_type == 'other' and result.confidence < 0.8
    provider.generate.assert_called_once()


def test_timeout_fallback(db, graph):
    opening(db, graph[-1], '')
    provider = Mock(); provider.generate.side_effect = AITransientError('timeout')
    service = ResourceClassificationService(provider, max_llm_calls=1)
    assert service.classify(db, graph[-1], metadata={'filename':'Notes.pdf'}).resource_type == 'other'
    assert service.llm_calls == 1


def test_manual_skips_reclassification_content_and_llm(db, graph, client, monkeypatch):
    resource = graph[-1]
    response = client.patch(f'/api/resources/{resource.id}/classification', json={'resource_type':'lecture'})
    assert response.json()['classification_confidence'] == 1.0
    monkeypatch.setattr('app.services.resource_classification.early_text', Mock(side_effect=AssertionError()))
    provider = Mock()
    result = ResourceClassificationService(provider, max_llm_calls=1).apply(
        db, resource, metadata={'filename':'Tutorial.pdf'})
    db.commit(); db.refresh(resource)
    assert result.method == 'manual' and resource.resource_type == 'lecture'
    provider.generate.assert_not_called()


def test_manual_committed_during_provider_request_wins(db, graph):
    resource = graph[-1]
    opening(db, resource, '')
    def generate(*args):
        db.execute(update(Resource).where(Resource.id == resource.id).values(
            resource_type='tutorial', classification_source='manual').execution_options(synchronize_session=False))
        return '{"resource_type":"lecture","confidence":0.9,"reason":"test"}'
    provider = Mock(); provider.generate.side_effect = generate
    result = ResourceClassificationService(provider, max_llm_calls=1).apply(db, resource, metadata={'filename':'Notes.pdf'})
    db.commit(); db.refresh(resource)
    assert resource.resource_type == 'tutorial' and resource.classification_source == 'manual'
    assert result.method == 'manual' and result.resource_type == 'tutorial'


def test_content_and_metadata_payload_bounded(db, graph):
    resource = graph[-1]
    opening(db, resource, 'x' * 5000)
    assert len(early_text(db, resource.id)) == 1000
    provider = Mock(); provider.generate.return_value = '{}'
    ResourceClassificationService(provider, max_llm_calls=1).classify(db, resource,
        metadata={'filename':'Notes.pdf','nearby_text':'x'*10000,'arbitrary_secret':'do not send'})
    payload = json.loads(provider.generate.call_args.args[1])
    assert len(payload['metadata']['nearby_text']) == 500
    assert 'arbitrary_secret' not in payload['metadata']


def test_unchanged_sync_uses_existing_content_without_reprocessing(db, sync_setup):
    run(db, sync_setup)
    resource = db.scalar(select(Resource))
    resource.filename = sync_setup[1].metadata[201].filename = 'Notes.pdf'
    opening(db, resource, 'Lecture\nOverview')
    before = (len(sync_setup[1].downloads), sync_setup[2].parse.call_count, sync_setup[5].call_count)
    result = run(db, sync_setup)
    db.refresh(resource)
    assert resource.resource_type == 'lecture' and resource.classification_method == 'document_content'
    assert result.files_skipped == 1
    assert before == (len(sync_setup[1].downloads), sync_setup[2].parse.call_count, sync_setup[5].call_count)


def test_reclassification_cli_preview_does_not_write(tmp_path, monkeypatch, capsys):
    from app import reclassify
    from app.core.config import Settings
    from app.core.database import build_engine, init_db
    from app.models import Semester, Course, Week
    from sqlalchemy.orm import Session
    url = f'sqlite:///{tmp_path / "classification.db"}'
    engine = build_engine(url); init_db(engine)
    with Session(engine) as db:
        semester = Semester(name='Test', year=2026, term='S1'); db.add(semester); db.flush()
        course = Course(semester_id=semester.id, name='Test', code='TEST'); db.add(course); db.flush()
        week = Week(course_id=course.id, week_number=1, title='Week 1'); db.add(week); db.flush()
        resource = Resource(week_id=week.id, filename='Lecture.pdf', file_type='pdf')
        db.add(resource); db.commit(); rid = resource.id
    monkeypatch.setattr(reclassify, 'Settings', lambda: Settings(_env_file=None, database_url=url))
    assert reclassify.main(['--resource-id', str(rid)]) == 0
    with engine.connect() as conn:
        assert conn.execute(text('select resource_type from resources')).scalar_one() == 'other'
    assert reclassify.main(['--resource-id', str(rid), '--apply']) == 0
    with engine.connect() as conn:
        assert conn.execute(text('select resource_type from resources')).scalar_one() == 'lecture'
    assert 'LLM requests: 0' in capsys.readouterr().out
