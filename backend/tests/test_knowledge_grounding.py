import json

import httpx2 as httpx
import pytest
from sqlalchemy import select, func

from app.models import Concept, DocumentChunk, Resource, ResourceKnowledge, Summary
from app.schemas.knowledge import provider_output_schema
from app.services.ai_errors import AIResponseError, KnowledgeInputError
from app.services.ai_service import encode_batch
from app.services.knowledge_grounding import has_exam_cue
from test_knowledge import ai, chunk, payload, FakeProvider, prepared
from test_deepseek import settings
from app.services.deepseek_provider import DeepSeekProvider


def test_chunk_identity_and_application_evidence():
    data = payload(8, 'rewritten quotation', chunk_id=117)
    source = chunk(8, 'Frames\n  carry data.').model_copy(update={'source_chunk_id': 117})
    result = ai(FakeProvider([data])).extract([source])
    item = result.knowledge.concepts[0]
    assert item.source_chunk_ids == [117]
    assert item.source_pages == [8]
    assert item.evidence[0].quote == source.content
    assert item.evidence[0].source_chunk_id == 117
    assert '[CHUNK_ID=117 | PAGE=8]' in encode_batch([source])
    assert 'rewritten quotation' not in result.model_dump_json()


def test_whitespace_and_unicode_debug_quote_ignored():
    data = payload(1, 'Frames carry data - example.')
    source = chunk(content='Frames\ncarry data — example.')
    result = ai(FakeProvider([data])).extract([source])
    assert result.knowledge.concepts[0].evidence[0].quote == source.content


def test_interleaved_text_and_layout_warnings_preserved():
    text = 'receiving side– sending side:\n  errors  – encapsulates datagram\n upper layer   frame'
    source = chunk(8, text, ['layout_review_recommended'])
    result = ai(FakeProvider([payload(8)])).extract([source])
    item = result.knowledge.concepts[0]
    assert item.evidence[0].quote == text
    assert item.source_warnings == ['layout_review_recommended']


@pytest.mark.parametrize('ids,pages', [([999], [1]), ([1], [999]), ([1, 1], [1]), ([1], [1, 1])])
def test_bad_provenance_rejects_core(ids, pages):
    data = payload()
    data['concepts'][0].update(source_chunk_ids=ids, source_pages=pages)
    with pytest.raises(AIResponseError):
        ai(FakeProvider([data]), llm_max_retries=0).extract([chunk()])


def test_cross_resource_input_rejected_before_provider():
    provider = FakeProvider()
    foreign = chunk(2).model_copy(update={'resource_id': 2})
    with pytest.raises(KnowledgeInputError):
        ai(provider).extract([chunk(), foreign])
    assert provider.calls == []


def test_foreign_database_chunk_id_rejected(db, prepared):
    service, resource = prepared
    other = Resource(week_id=resource.week_id, filename='other.pdf', file_type='pdf')
    db.add(other)
    db.flush()
    foreign = DocumentChunk(resource_id=other.id, page_number=1, chunk_index=0, content='Frames carry data.')
    db.add(foreign)
    db.commit()
    with pytest.raises(AIResponseError):
        service.generate(db, resource.id, ai(FakeProvider([payload(chunk_id=foreign.id)]), llm_max_retries=0))
    assert db.get(ResourceKnowledge, resource.id) is None


@pytest.mark.parametrize('cue', ['Exam: frames', 'Assessment: frames', 'Quiz: frames',
                                'Important: frames', 'Remember frames', 'Learning outcome: frames',
                                'Final test: frames', '考试：帧'])
def test_explicit_exam_cues_retained(cue):
    data = payload()
    data['exam_focus'] = [data['key_points'][0]]
    result = ai(FakeProvider([data])).extract([chunk(content=cue)])
    assert len(result.knowledge.exam_focus) == 1
    assert result.exam_focus_omitted == 0


@pytest.mark.parametrize('text', ['Frame structure', 'CRC error test', 'Test the checksum.',
                                 'Not on the exam.', 'This is not important.', 'No quiz.'])
def test_technical_or_negated_exam_cues_do_not_count(text):
    assert not has_exam_cue(text)


def test_model_quote_cannot_supply_exam_cue():
    data = payload(quote='Important for exam!')
    data['exam_focus'] = [data['key_points'][0]]
    result = ai(FakeProvider([data])).extract([chunk()])
    assert result.knowledge.exam_focus == []
    assert result.exam_focus_omitted == 1
    assert len(result.knowledge.concepts) == 1


def test_optional_exam_bad_citation_filtered():
    data = payload()
    data['exam_focus'] = [dict(data['key_points'][0], source_chunk_ids=[999])]
    result = ai(FakeProvider([data])).extract([chunk()])
    assert result.exam_focus_omitted == 1
    assert result.optional_items_omitted == {'exam_focus': 1}


@pytest.mark.parametrize('category,field', [('concepts', 'definition'), ('concepts', 'explanation'),
    ('key_points', 'content'), ('questions', 'question'), ('questions', 'answer'),
    ('examples', 'description'), ('exam_focus', 'content')])
@pytest.mark.parametrize('formula', ['2^(N-1)', r'\frac{1}{N}', 'x²', 'a_b=2'])
def test_formula_reconstruction_guard_across_prose(category, field, formula):
    data = payload()
    if category == 'examples':
        data[category] = [dict(source_chunk_ids=[1], source_pages=[1], description=formula)]
    elif category == 'exam_focus':
        data[category] = [dict(data['key_points'][0])]
    data[category][0][field] = formula
    source = chunk(content='Important: Frames carry data. 2(N-1)', warnings=['suspicious_formula_layout'])
    service = ai(FakeProvider([data]), llm_max_retries=0)
    result = service.extract([source])
    if category == 'concepts' and field == 'explanation':
        assert result.knowledge.concepts[0].explanation == ''
        assert result.formula_reduced_counts[category] == 1
    else:
        assert getattr(result.knowledge, category) == []
        assert result.formula_filtered_counts[category] == 1


def test_warned_literal_math_removed_but_safe_explanation_retained_and_marked():
    data = payload()
    data['concepts'][0]['definition'] = 'Frames carry data. r+1 bits.'
    data['concepts'][0]['explanation'] = 'Frames carry data.'
    result = ai(FakeProvider([data])).extract([
        chunk(content='Frames carry data. r+1 bits.', warnings=['suspicious_formula_layout'])])
    assert result.knowledge.concepts[0].source_warnings == ['suspicious_formula_layout']
    assert result.knowledge.concepts[0].evidence[0].warnings == ['suspicious_formula_layout']
    assert result.knowledge.concepts[0].definition == ''
    assert result.knowledge.concepts[0].explanation == 'Frames carry data.'


def test_mixed_citations_do_not_launder_reconstruction():
    data = payload()
    data['concepts'][0].update(source_chunk_ids=[1, 2], source_pages=[1, 2], definition='x^2')
    result = ai(FakeProvider([data]), llm_max_retries=0).extract([
        chunk(content='x2', warnings=['suspicious_formula_layout']), chunk(2)])
    assert result.knowledge.concepts == []
    assert result.formula_filtered_counts['concepts'] == 1


def test_overview_cannot_bypass_warned_formula_guard():
    data = payload()
    data['overview'] = 'The formula is 2^(N-1).'
    result = ai(FakeProvider([data]), llm_max_retries=0).extract([
        chunk(content='2(N-1)', warnings=['suspicious_formula_layout'])])
    assert '2^(N-1)' not in result.knowledge.overview


def test_split_chunk_retains_original_id_and_full_evidence():
    source = chunk(content='Frames carry data. ' * 150)
    result = ai(FakeProvider(), llm_batch_characters=1000).extract([source])
    assert result.batches > 1
    assert all(e.source_chunk_id == 1 and e.quote == source.content
               for c in result.knowledge.concepts for e in c.evidence)


def test_valid_core_persists_despite_five_filtered_exam_items(db, prepared):
    service, resource = prepared
    stored = db.scalar(select(DocumentChunk).where(DocumentChunk.resource_id == resource.id))
    data = payload(chunk_id=stored.id)
    data['concepts'] = [dict(data['concepts'][0], name=f'Concept {i}') for i in range(8)]
    data['key_points'] = [dict(data['key_points'][0], content=f'Point {i}') for i in range(14)]
    data['questions'] = [dict(data['questions'][0], question=f'Question {i}') for i in range(3)]
    data['exam_focus'] = [dict(data['key_points'][0], content=f'Exam {i}') for i in range(5)]
    result = service.generate(db, resource.id, ai(FakeProvider([data])))
    assert result.extraction.exam_focus_omitted == 5
    assert result.extraction.generated_counts['exam_focus'] == 5
    assert db.scalar(select(func.count()).select_from(Concept)) == 8
    assert len(result.extraction.knowledge.key_points) == 14
    assert len(result.extraction.knowledge.questions) == 3
    assert db.scalar(select(Summary)).exam_focus == []
    assert service.read(db, resource.id).extraction.knowledge.concepts[0].evidence[0].quote == stored.content


def test_provider_schema_has_required_ids_and_no_model_evidence():
    schema = provider_output_schema()
    for definition in [schema, *schema['$defs'].values()]:
        if 'properties' in definition:
            assert set(definition['required']) == set(definition['properties'])
            assert definition['additionalProperties'] is False
            assert 'evidence' not in definition['properties']
    assert 'source_chunk_ids' in schema['$defs']['KnowledgeConcept']['properties']


def test_deepseek_usage_captured_before_empty_response_rejection():
    body = {'usage': {'prompt_tokens': 9, 'completion_tokens': 0, 'total_tokens': 9,
                     'prompt_cache_hit_tokens': 4, 'prompt_cache_miss_tokens': 5, 'secret': 'private'},
            'choices': [{'finish_reason': 'stop', 'message': {'content': ''}}]}
    provider = DeepSeekProvider(settings(), transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    with pytest.raises(AIResponseError):
        provider.generate('s', 'u', {})
    assert provider.request_usage == [{'request': 1, 'model': 'deepseek-flash', 'http_status': 200,
                                      'prompt_tokens': 9, 'completion_tokens': 0, 'total_tokens': 9,
                                      'prompt_cache_hit_tokens': 4, 'prompt_cache_miss_tokens': 5}]
