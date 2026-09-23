import json

import pymupdf
import pytest
from sqlalchemy import select

from app.models import DocumentChunk, ResourceKnowledge
from app.services.ai_errors import AIResponseError
from app.services.document_processing import process_resource
from app.services.knowledge_input import MATH_OMITTED, mask_warned_math, prepare_ai_chunks
from test_knowledge import ai, chunk, payload, FakeProvider, prepared


@pytest.mark.parametrize('text', ['P(success) = (1-p)2(N-1)', 'x²', r'\frac{1}{N}', 'a_b=2', 'p=0.04'])
def test_warning_aware_masking_preserves_prose_and_original(text):
    original = 'Frames carry data.\n' + text + '\nData-link service is useful.\n'
    source = chunk(8, original, ['suspicious_formula_layout']).model_copy(update={'source_chunk_id': 117})
    prepared, stats = prepare_ai_chunks([source])
    assert source.content == original
    assert text not in prepared[0].content
    assert MATH_OMITTED in prepared[0].content
    assert prepared[0].content.startswith('Frames carry data.\n')
    assert prepared[0].content.endswith('\nData-link service is useful.\n')
    assert prepared[0].source_chunk_id == 117 and prepared[0].page_number == 8
    assert prepared[0].chunk_index == source.chunk_index
    assert stats['chunks_masked'] == 1 and stats['segments_masked'] >= 1


@pytest.mark.parametrize('warnings', [[], ['repeated_header_footer'], ['layout_review_recommended']])
def test_no_formula_layout_warning_no_masking(warnings):
    assert mask_warned_math('P(success) = (1-p)2(N-1)', warnings) == ('P(success) = (1-p)2(N-1)', 0)


def test_safe_prose_on_warned_page_remains_unchanged():
    text = 'TCP\nData-link service carries frames.\nSingle-bit errors.\n41'
    assert mask_warned_math(text, ['suspicious_formula_layout']) == (text, 0)


def test_local_filtering_preserves_safe_siblings_before_semantic_review():
    data = payload()
    concept = data['concepts'][0]
    data['concepts'] += [dict(concept, name='Unsafe', definition='x^2'),
                         dict(concept, name='Reduced', explanation='x^2')]
    data['key_points'] += [dict(data['key_points'][0], content='x^2'),
                           dict(data['key_points'][0], content='Unsupported statement')]
    data['questions'].append(dict(data['questions'][0], answer='x^2'))
    data['examples'] = [dict(source_chunk_ids=[1], source_pages=[1], description='x^2')]
    data['exam_focus'] = [dict(data['key_points'][0], content='x^2')]
    data['formulas'] = [dict(source_chunk_ids=[1], source_page=1, formula='x^2', explanation=None, reliable=True)]
    provider = FakeProvider([data], semantic_judge=lambda c, s: c['text'] != 'Unsupported statement')
    original = 'Important: Frames carry data. x2'
    result = ai(provider, llm_max_retries=0).extract([chunk(content=original, warnings=['suspicious_formula_layout'])])
    assert len(provider.calls) == 1 and provider.semantic_calls
    assert [c.name for c in result.knowledge.concepts] == ['Frame', 'Reduced']
    assert result.knowledge.concepts[1].definition == 'Carries data'
    assert result.knowledge.concepts[1].explanation == ''
    assert len(result.knowledge.key_points) == len(result.knowledge.questions) == 1
    assert all(n == 1 for n in result.formula_filtered_counts.values())
    assert result.formula_reduced_counts['concepts'] == 1
    assert result.semantic_review.rejected_counts['key_points'] == 1
    for _, user, _ in provider.semantic_calls:
        assert 'x^2' not in user and 'Unsafe' not in user
    assert result.knowledge.concepts[0].evidence[0].quote == original


def test_generation_and_review_mask_prompts_but_evidence_remains_original():
    source = chunk(8, 'Frames carry data.\nP(success) = (1-p)2(N-1)', ['suspicious_formula_layout'])
    provider = FakeProvider([payload(8)])
    result = ai(provider).extract([source])
    for _, user, _ in provider.calls + provider.semantic_calls:
        assert MATH_OMITTED in user
        assert '(1-p)2(N-1)' not in user
    assert result.knowledge.concepts[0].evidence[0].quote == source.content
    assert result.input_masking['chunks_masked'] == 1


def test_name_or_both_concept_fields_unsafe_drops_only_affected_concept():
    data = payload()
    data['concepts'] += [dict(data['concepts'][0], name='x^2'),
                         dict(data['concepts'][0], definition='x^2', explanation='x^2')]
    result = ai(FakeProvider([data])).extract([chunk(content='x2', warnings=['suspicious_formula_layout'])])
    assert len(result.knowledge.concepts) == 1
    assert result.formula_filtered_counts['concepts'] == 2


def test_source_failure_is_not_disguised_as_formula_filtering():
    data = payload()
    data['concepts'][0].update(definition='x^2', source_chunk_ids=[999])
    provider = FakeProvider([data])
    with pytest.raises(AIResponseError):
        ai(provider, llm_max_retries=0).extract([chunk(warnings=['suspicious_formula_layout'])])
    assert provider.semantic_calls == []


def test_decimal_expression_cannot_match_only_its_integer_prefix():
    data = payload()
    data['key_points'][0]['content'] = 'p=0.04'
    result = ai(FakeProvider([data])).extract([
        chunk(content='p=0.02', warnings=['suspicious_formula_layout'])])
    assert result.formula_filtered_counts['key_points'] == 1
    assert result.knowledge.key_points == []


def test_stored_source_unchanged_and_failed_reprocessing_atomic(db, prepared):
    service, resource = prepared
    path = resource.local_path
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((50, 100), 'x', fontsize=20)
    page.insert_text((61, 94), '2', fontsize=12)  # Actual structured extraction warning.
    page.insert_text((50, 150), 'Frames carry data. x = 2', fontsize=12)
    document.save(path)
    document.close()
    process_resource(db, resource.id, service.documents)
    stored = db.scalar(select(DocumentChunk).where(DocumentChunk.resource_id == resource.id))
    before = (stored.id, stored.page_number, stored.chunk_index, stored.content)
    data = payload(chunk_id=stored.id)
    data['concepts'][0]['explanation'] = 'x^2'
    provider = FakeProvider([data])
    result = service.generate(db, resource.id, ai(provider))
    assert result.extraction.input_masking['chunks_masked'] == 1
    assert result.extraction.formula_reduced_counts['concepts'] == 1
    assert result.extraction.knowledge.concepts[0].evidence[0].quote == before[3]
    saved = json.dumps(db.get(ResourceKnowledge, resource.id).payload, sort_keys=True)
    broken = FakeProvider([data], semantic_responses=['invalid json'])
    with pytest.raises(AIResponseError):
        service.generate(db, resource.id, ai(broken, llm_max_retries=0))
    db.expire_all()
    assert json.dumps(db.get(ResourceKnowledge, resource.id).payload, sort_keys=True) == saved
    stored = db.get(DocumentChunk, before[0])
    assert (stored.id, stored.page_number, stored.chunk_index, stored.content) == before
