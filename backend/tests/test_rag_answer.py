import json
from dataclasses import replace
from unittest.mock import Mock

import pytest

from app.models import DocumentChunk
from app.models.common import ResourceStatus
from app.services.ai_errors import AIResponseError, AITransientError
from app.services.rag_answer_service import RAGAnswerService, INSUFFICIENT, SYSTEM_PROMPT
from app.services.rag_answer_context import select_answer_context, exercise_prompt
from app.services.retrieval_service import RetrievalHit, RetrievalService
from evals import rag_answer


def hit(i):
    return RetrievalHit(chunk_id=i, score=1/i, text=f'Synthetic source fact {i}.',
        resource_id=i, resource_title=f'Lesson {i}.pdf', course_id=1, course_code='TEST',
        course_name='Synthetic', week_id=1, week_title='Week 1', page_number=i,
        resource_type='other', source_link=f'/api/resources/{i}/file#page={i}',
        parsing_warnings=['suspicious_formula_layout'] if i == 5 else [], parsing_health='good')


@pytest.fixture
def service():
    retriever = Mock()
    retriever.search.return_value = [hit(i) for i in range(1, 6)]
    reranker = Mock()
    reranker.score.return_value = [1., 2., 3., 4., 5.]
    provider = Mock()
    provider.generate.return_value = json.dumps({'answerable': True, 'answer': 'Source fact [1].', 'citation_ids': [1]})
    return RAGAnswerService(retriever, reranker, provider)


def test_top_three_context_and_server_owned_citations(service):
    result = service.answer(None, 1, '解释这个概念')
    service.retrieval.search.assert_called_once_with(None, 1, '解释这个概念', top_k=5, resource_types=None)
    system, payload, schema = service.provider.generate.call_args.args
    evidence = json.loads(payload)['evidence']
    assert [e['chunk_id'] for e in evidence] == [5, 4, 3]
    assert evidence[0]['parsing_warnings'] == ['suspicious_formula_layout']
    assert all('score' not in e and 'rerank_score' not in e for e in evidence)
    assert system == SYSTEM_PROMPT and 'JSON' in system and 'external knowledge' in system
    assert 'plain text' in system and 'Do not use Markdown bold' in system
    assert schema['additionalProperties'] is False
    assert result.sources[0].model_dump() == {k: v for k, v in evidence[0].items() if k not in {'text', 'parsing_warnings'}}
    assert result.sources[0].page == 5 and result.sources[0].title == 'Lesson 5.pdf'


def test_no_evidence_no_llm(service):
    service.retrieval.search.return_value = []
    result = service.answer(None, 1, 'Unknown?')
    assert result.answer == INSUFFICIENT and not result.answerable and result.sources == []
    service.provider.generate.assert_not_called()
    service.reranker.score.assert_not_called()


def test_type_filter(service):
    service.answer(None, 1, 'q', resource_type='tutorial', top_k=1)
    assert service.retrieval.search.call_args.kwargs['resource_types'] == ['tutorial']
    assert len(json.loads(service.provider.generate.call_args.args[1])['evidence']) == 1


def test_week_filter_post_rerank(db, graph, service):
    _, course, week, _ = graph
    service.retrieval.search.return_value = [replace(hit(i), course_id=course.id,
        week_id=week.id if i < 3 else week.id+1) for i in range(1, 6)]
    evidence = service.prepare(db, course.id, 'q', week_id=week.id)
    assert [e.chunk_id for e in evidence] == [2, 1]
    assert service.retrieval.search.call_args.kwargs['top_k'] == 5
    service.reranker.score.assert_called_once()
    with pytest.raises(ValueError, match='Week does not belong'):
        service.prepare(db, course.id, 'q', week_id=999)


@pytest.mark.parametrize('kwargs', [{'top_k': 4}, {'top_k': True}, {'resource_type': 'reading'}, {'week_id': -1}])
def test_invalid_scope_never_calls_llm(service, kwargs):
    with pytest.raises(ValueError):
        service.answer(None, 1, 'q', **kwargs)
    service.provider.generate.assert_not_called()


@pytest.mark.parametrize('raw', ['', 'not json', '{}',
    '{"answerable":true,"answer":"Invented [99]","citation_ids":[99]}',
    '{"answerable":true,"answer":"No citation","citation_ids":[]}',
    '{"answerable":true,"answer":"Wrong [2]","citation_ids":[1]}',
    '{"answerable":true,"answer":"Duplicate [1]","citation_ids":[1,1]}',
    '{"answerable":true,"answer":"Fake [1]","citation_ids":[1],"sources":[{"page":999,"title":"fake"}]}',
    '{"answerable":false,"answer":"Cannot answer [1]","citation_ids":[1]}',
    '{"answerable":true,"answer":"Fake [1]","citation_ids":[true]}'])
def test_invalid_output_fails_closed_without_retry(service, raw):
    service.provider.generate.return_value = raw
    with pytest.raises(AIResponseError, match='Invalid RAG JSON'):
        service.answer(None, 1, 'q')
    assert service.provider.generate.call_count == 1


def test_provider_abstention(service):
    service.provider.generate.return_value = '{"answerable":false,"answer":"Not enough context","citation_ids":[]}'
    result = service.answer(None, 1, 'q')
    assert result.answer == INSUFFICIENT and result.sources == []


def test_provider_failure_is_not_a_fake_answer(service):
    service.provider.generate.side_effect = AITransientError('Unavailable')
    with pytest.raises(AITransientError):
        service.answer(None, 1, 'q')
    assert service.provider.generate.call_count == 1


def test_real_retrieval_and_rerank_with_synthetic_embeddings(db, graph):
    _, course, _, resource = graph
    resource.sync_status = ResourceStatus.parsed
    db.add_all([DocumentChunk(resource=resource, page_number=i, chunk_index=i-1,
        content=f'This synthetic learning concept has explanatory body text numbered {i}.') for i in range(1, 7)])
    db.commit()
    embedding = Mock(model='synthetic', model_version='1', dimensions=2)
    embedding.embed.return_value = [[1., 0.]] * 6
    embedding.embed_query.return_value = [1., 0.]
    retrieval = RetrievalService(embedding)
    retrieval.index_course(db, course.id)
    reranker = Mock()
    reranker.score.return_value = [1., 2., 3., 4., 5.]
    llm = Mock()
    llm.generate.return_value = '{"answerable":true,"answer":"A fact [1][2]","citation_ids":[1,2]}'
    result = RAGAnswerService(retrieval, reranker, llm).answer(db, course.id, 'Explain it')
    assert [s.page for s in result.sources] == [5, 4]
    assert all(s.resource_id == resource.id for s in result.sources)
    assert len(reranker.score.call_args.args[1]) == 5
    assert len(json.loads(llm.generate.call_args.args[1])['evidence']) == 3


def test_preview_cli_does_not_create_paid_provider(monkeypatch, capsys, service):
    monkeypatch.setattr(rag_answer, 'load_runtime', lambda *a: (Mock(), service))
    factory = Mock(side_effect=AssertionError('Must not construct provider'))
    monkeypatch.setattr(rag_answer, 'create_llm_provider', factory)
    assert rag_answer.main(['--course-id', '1', '--question', 'q']) == 0
    factory.assert_not_called()
    service.provider.generate.assert_not_called()
    assert 'Preview only' in capsys.readouterr().out


def test_explicit_generation_cli(monkeypatch, capsys, service):
    monkeypatch.setattr(rag_answer, 'load_runtime', lambda *a: (Mock(), service))
    monkeypatch.setattr(rag_answer, 'create_llm_provider', lambda *a: service.provider)
    assert rag_answer.main(['--course-id', '1', '--question', 'q', '--generate']) == 0
    output = capsys.readouterr().out
    assert 'Answer:' in output and 'Sources:' in output and 'p.5' in output
    service.provider.generate.assert_called_once()


def test_review_template_reuses_gold_without_generation(tmp_path, monkeypatch):
    rows = [{'sample_id': 'Q01', 'question': 'Synthetic?', 'course_id': 1,
             'expected_resource_id': 1, 'expected_pages': [3]}]
    dataset = tmp_path / 'gold.json'
    dataset.write_text(json.dumps(rows), encoding='utf-8')
    before = dataset.read_bytes()
    monkeypatch.setattr(rag_answer, 'load_runtime', Mock(side_effect=AssertionError('No models')))
    output = tmp_path / 'reviews.json'
    assert rag_answer.main(['--course-id', '1', '--dataset', str(dataset), '--review-template', str(output)]) == 0
    review = json.loads(output.read_text('utf-8'))[0]
    assert all(review[key] is None for key in ['answerable', 'citation_correct', 'grounded'])
    assert review['expected_pages'] == [3] and dataset.read_bytes() == before


@pytest.fixture
def mixed_context(db, graph):
    _, course, week, resource = graph
    resource.sync_status = ResourceStatus.parsed
    resource.local_path = 'materials/synthetic.pdf'
    resource.parsing_report = {'health': {'status': 'review', 'issues': [
        {'page_number': 11, 'category': 'suspicious_formula_layout'}]}}
    body = ('The source explains how the sender performs the calculation and how the receiver '
            'checks the result. Each operation follows the procedure described in this material.')
    pages = {9: 'XYZ Arithmetic', 10: 'XYZ Division', 11: 'XYZ Definition',
             12: 'XYZ Example', 13: 'XYZ Steps', 14: 'Different Section'}
    chunks = [DocumentChunk(resource=resource, page_number=p, chunk_index=p-1,
        content=title + ('\n' + body if p != 10 else '')) for p, title in pages.items()]
    db.add_all(chunks)
    db.commit()
    lectures = {c.page_number: replace(hit(c.id), chunk_id=c.id, resource_id=resource.id,
        resource_title=resource.filename, course_id=course.id, week_id=week.id,
        page_number=c.page_number, text=c.content, resource_type='other') for c in chunks}
    prompts = [replace(hit(i), resource_title='Assignment.pdf', text=f'Question {i}. Calculate XYZ.')
               for i in (800, 801)]
    return [*prompts, lectures[10], lectures[12], lectures[13]], chunks


def test_context_balances_exercises_and_expands_only_two_adjacent_pages(db, mixed_context):
    ranked, chunks = mixed_context
    before = [(c.id, c.content, c.page_number) for c in chunks]
    selected = select_answer_context(db, ranked, 'XYZ 是什么？', 3)
    assert [h.page_number for h in selected] == [12, 13, 800, 11, 9]
    assert len(selected) == 5 and sum(exercise_prompt(h) for h in selected) == 1
    assert selected[3].parsing_warnings == ['suspicious_formula_layout']
    assert selected[3].source_link.endswith('#page=11')
    assert selected[3].resource_id == ranked[2].resource_id
    assert len({h.chunk_id for h in selected}) == 5
    assert [(c.id, c.content, c.page_number) for c in chunks] == before
    assert ranked[0].chunk_id == 800  # Retrieval order is not mutated.


def test_unmatched_heading_does_not_expand(db, mixed_context):
    ranked, _ = mixed_context
    lecture_ranked = [replace(h, resource_type='lecture') if i >= 2 else h for i, h in enumerate(ranked)]
    selected = select_answer_context(db, lecture_ranked, 'Unrelated topic', 3)
    assert len(selected) == 3


def test_no_explanatory_body_preserves_existing_context(mixed_context):
    ranked, _ = mixed_context
    assert select_answer_context(None, ranked[:3], 'XYZ', 3) == ranked[:3]
    assert select_answer_context(None, ranked[2:], 'XYZ', 3) == ranked[2:]


def test_worked_tutorial_solution_is_not_an_unanswered_exercise():
    assert not exercise_prompt(replace(hit(1), resource_title='Tutorial.pdf',
        text='Question 1. Calculate XYZ.\nSolution: follow these steps.'))


def test_unusable_neighbor_is_not_added(db, mixed_context):
    ranked, _ = mixed_context
    from app.models import Resource
    resource = db.get(Resource, ranked[2].resource_id)
    resource.sync_status = ResourceStatus.pending
    db.flush()
    assert len(select_answer_context(db, ranked, 'XYZ', 3)) == 3


def test_expanded_citation_five_keeps_validation(service):
    from app.services.rag_answer_service import AnswerEvidence
    base = service.prepare(None, 1, 'q')
    evidence = base + [AnswerEvidence(**{**base[0].model_dump(), 'citation_id': i, 'chunk_id': 100+i})
                       for i in (4, 5)]
    service.provider.generate.return_value = '{"answerable":true,"answer":"Source [5]","citation_ids":[5]}'
    result = service.generate('q', evidence)
    assert result.sources[0].chunk_id == 105
    service.provider.generate.return_value = '{"answerable":true,"answer":"Fake [6]","citation_ids":[6]}'
    with pytest.raises(AIResponseError):
        service.generate('q', evidence)


@pytest.fixture
def continuous_pages(db, graph):
    _, course, week, resource = graph
    resource.sync_status = ResourceStatus.parsed
    resource.resource_type = 'lecture'
    resource.local_path = 'materials/synthetic.pdf'
    body = ('This source describes a practical procedure for testing an idea with participants. '
            'The following instructions explain the activity and the observations to record during each session.')
    chunks = [DocumentChunk(resource=resource, page_number=p, chunk_index=p-21,
        content=f'Testing a design\n{p}. {body}') for p in range(21, 30)]
    db.add_all(chunks); db.commit(); db.expire_all()
    return {c.page_number: replace(hit(c.id), course_id=course.id, week_id=week.id,
        resource_id=resource.id, resource_title=resource.filename, resource_type='lecture',
        page_number=c.page_number, text=c.content) for c in chunks}


def test_continuity_bridges_same_resource_gap_with_real_source(db, continuous_pages):
    ranked = [continuous_pages[p] for p in (22, 24)]
    selected = select_answer_context(db, ranked, 'What is testing a design?', 3)
    assert [h.page_number for h in selected] == [22, 24, 23]
    assert selected[-1].source_link.endswith('#page=23')
    assert selected[-1].resource_id == ranked[0].resource_id
    assert selected[-1].course_id == ranked[0].course_id
    assert len(ranked) == 2


@pytest.mark.parametrize('mismatch', ['resource', 'section', 'course', 'unusable', 'cover'])
def test_continuity_rejects_unrelated_or_invalid_evidence(db, continuous_pages, mismatch):
    from app.models import Resource
    left, right = [continuous_pages[p] for p in (22, 24)]
    middle = db.get(DocumentChunk, continuous_pages[23].chunk_id)
    if mismatch == 'resource':
        other = Resource(week_id=right.week_id, filename='Other.pdf', file_type='pdf',
                         sync_status=ResourceStatus.parsed, resource_type='lecture')
        db.add(other); db.flush()
        chunk = db.get(DocumentChunk, right.chunk_id); chunk.resource_id = other.id
        right = replace(right, resource_id=other.id)
    elif mismatch == 'section':
        middle.content = middle.content.replace('Testing a design', 'Another unrelated topic')
    elif mismatch == 'course':
        left = replace(left, course_id=999)
        right = replace(right, course_id=999)
    elif mismatch == 'unusable':
        db.get(Resource, left.resource_id).sync_status = ResourceStatus.pending
    else:
        middle.content = 'Testing a design'  # Heading-only page is not body evidence.
    db.flush()
    assert select_answer_context(db, [left, right], 'What is testing a design?', 3) == [left, right]


def test_continuity_is_bounded_and_does_not_expand_outwards(db, continuous_pages):
    ranked = [continuous_pages[p] for p in (22, 25, 28)]
    selected = select_answer_context(db, ranked, 'What is testing a design?', 3)
    assert [h.page_number for h in selected] == [22, 25, 28, 23, 24]
    # A gap of three missing pages is outside the bound, even if headings match.
    ranked = [continuous_pages[p] for p in (22, 26)]
    assert select_answer_context(db, ranked, 'What is testing a design?', 3) == ranked
