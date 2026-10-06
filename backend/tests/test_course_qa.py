from unittest.mock import Mock

import pytest

from app.api.ask import get_course_qa
from app.services.ai_errors import AITransientError, AIConfigurationError
from app.services.rag_answer_service import RagAnswer, AnswerSource, INSUFFICIENT
from app.services.course_qa import CourseQAService


@pytest.fixture
def qa(client):
    service = Mock()
    service.ask.return_value = RagAnswer(answerable=True, answer='A source-supported fact [1].', sources=[
        AnswerSource(citation_id=1, chunk_id=1, resource_id=1, title='Lecture.pdf', course_id=1,
                     week_id=1, week='Week 2', page=17, resource_type='lecture',
                     source_url='/api/resources/1/file#page=17')])
    client.app.dependency_overrides[get_course_qa] = lambda: service
    yield service
    client.app.dependency_overrides.clear()


def test_successful_ask_and_sources(client, graph, qa):
    course, week = graph[1:3]
    response = client.post(f'/api/courses/{course.id}/ask', json={
        'question': '  What is this?  ', 'week_id': week.id, 'resource_type': 'lecture'})
    assert response.status_code == 200
    assert response.json() == qa.ask.return_value.model_dump()
    assert response.json()['sources'][0]['page'] == 17
    assert qa.ask.call_args.args[1:] == (course.id, 'What is this?')
    assert qa.ask.call_args.kwargs == {'week_id': week.id, 'resource_type': 'lecture'}


@pytest.mark.parametrize('question', ['', ' \n ', 'a'*4001, 123, None])
def test_invalid_question(client, graph, qa, question):
    assert client.post(f'/api/courses/{graph[1].id}/ask', json={'question': question}).status_code == 422
    qa.ask.assert_not_called()


def test_missing_course_and_wrong_week(client, graph, qa):
    assert client.post('/api/courses/999/ask', json={'question': 'q'}).status_code == 404
    assert client.post(f'/api/courses/{graph[1].id}/ask', json={'question': 'q', 'week_id': 999}).status_code == 422
    qa.ask.assert_not_called()


def test_safe_service_failure(client, graph, qa):
    qa.ask.side_effect = AITransientError('Course Q&A temporarily unavailable.')
    response = client.post(f'/api/courses/{graph[1].id}/ask', json={'question': 'q'})
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'ai_temporarily_unavailable'


def test_abstention_serialization(client, graph, qa):
    qa.ask.return_value = RagAnswer(answerable=False, answer=INSUFFICIENT, sources=[])
    response = client.post(f'/api/courses/{graph[1].id}/ask', json={'question': 'q'})
    assert response.status_code == 200 and response.json()['sources'] == []


def test_adapter_uses_existing_service_without_llm_when_empty(db, engine, graph, monkeypatch):
    from app.services import course_qa
    service = Mock()
    service.prepare.return_value = []
    monkeypatch.setattr(course_qa, '_runtime', lambda: service)
    monkeypatch.setattr(course_qa, 'require_ready', lambda *args: None)
    factory = Mock(side_effect=AssertionError('No paid calls'))
    monkeypatch.setattr(course_qa, 'create_llm_provider', factory)
    result = CourseQAService().ask(db, graph[1].id, 'q')
    assert not result.answerable and result.sources == []
    factory.assert_not_called()


def test_stale_source_rejected_before_generation(db, engine, graph, monkeypatch):
    from app.services import course_qa
    service = Mock()
    service.prepare.return_value = [Mock(chunk_id=999, resource_id=graph[3].id, week_id=graph[2].id)]
    monkeypatch.setattr(course_qa, '_runtime', lambda: service)
    monkeypatch.setattr(course_qa, 'require_ready', lambda *args: None)
    factory = Mock(side_effect=AssertionError('No paid calls'))
    monkeypatch.setattr(course_qa, 'create_llm_provider', factory)
    with pytest.raises(AIConfigurationError, match='stale'):
        CourseQAService().ask(db, graph[1].id, 'q')
    factory.assert_not_called()
