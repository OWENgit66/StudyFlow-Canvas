import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import DocumentChunk, ResourceKnowledge
from app.schemas.knowledge import KnowledgeInput
from app.services.symbolic_safety import (UNREADABLE_SYMBOL, has_unreadable,
    mask_unreadable, unsafe_symbolic_content)
from app.services.knowledge_input import prepare_ai_chunks
from test_knowledge import FakeProvider, ai, chunk, payload, prepared


@pytest.mark.parametrize('glyph', ['\ue000', '\uf0c5', '\uf8ff', '\U000f0000', '\U0010fffd', '\ufffd', '\ufffc'])
def test_all_private_use_planes_and_replacement_characters(glyph):
    assert has_unreadable(glyph)
    assert mask_unreadable('CRC ' + glyph + ' R') == ('CRC ' + UNREADABLE_SYMBOL + ' R', 1)


def test_normal_unicode_is_not_unreadable():
    text = 'MAC 地址；α、é、🙂、⊕'
    assert not has_unreadable(text)
    assert mask_unreadable(text) == (text, 0)


@pytest.mark.parametrize('warnings', [[], ['suspicious_formula_layout']])
def test_glyph_masked_in_both_prompt_stages_original_evidence_unchanged(warnings):
    source = chunk(18, 'MAC addresses identify the source. A \uf0c5 B', warnings)
    snapshot = source.model_dump()
    data = payload(18)
    data['concepts'][0]['definition'] = 'MAC 地址用于帧头中识别源节点。'
    provider = FakeProvider([data])
    result = ai(provider).extract([source])
    for _, user, _ in provider.calls + provider.semantic_calls:
        assert UNREADABLE_SYMBOL in user and '\uf0c5' not in user
    assert source.model_dump() == snapshot
    item = result.knowledge.concepts[0]
    assert item.definition == data['concepts'][0]['definition']
    assert item.evidence[0].quote == source.content
    assert item.source_chunk_ids == [18] and item.source_pages == [18]


@pytest.mark.parametrize('operator', ['⊕', '⊗', '×', '÷', '±', '=', '→', '+', '-', '/', '*', '^'])
def test_guessed_operator_is_removed_without_warning_code(operator):
    source = chunk(content='A \uf0c5 B')
    data = payload()
    data['examples'] = [dict(source_chunk_ids=[1], source_pages=[1], description=f'A {operator} B')]
    provider = FakeProvider([data])
    result = ai(provider).extract([source])
    assert result.knowledge.examples == []
    assert result.formula_filtered_counts['examples'] == 1
    assert len(result.knowledge.concepts) == 1
    assert all(f'A {operator} B' not in call[1] for call in provider.semantic_calls)


@pytest.mark.parametrize('operator', ['⊕', '⊗', '×', '÷', '±', '=', '→'])
def test_operator_independently_present_in_reliable_cited_source_allowed(operator):
    text = f'A {operator} B'
    assert not unsafe_symbolic_content(text, [chunk(content=text)])
    assert not unsafe_symbolic_content(text, [chunk(content='A \uf0c5 B'), chunk(2, text)])
    assert unsafe_symbolic_content(text, [chunk(content='A \uf0c5 B'), chunk(2, 'Unrelated text')])


@pytest.mark.parametrize('warning', ['suspicious_formula_layout', 'unusual_symbol_position',
    'encoding_warning', 'layout_review_recommended'])
def test_warned_literal_symbolic_content_cannot_validate_itself(warning):
    assert unsafe_symbolic_content('x + 2', [chunk(content='x + 2', warnings=[warning])])


@pytest.mark.parametrize('expression', ['A = ... = B', 'Result = … = 7', 'A = ⋯ = B',
    'A = [MATHEMATICAL EXPRESSION OMITTED — PDF layout is unreliable] = 20'])
def test_malformed_equation_rejected_even_when_literal_source_and_no_warning(expression):
    data = payload()
    data['examples'] = [dict(source_chunk_ids=[1], source_pages=[1], description=expression)]
    result = ai(FakeProvider([data])).extract([chunk(content=expression)])
    assert result.knowledge.examples == []
    assert result.formula_filtered_counts['examples'] == 1


@pytest.mark.parametrize('text', ['MAC 地址用于帧头中识别源节点。',
    'The equals sign (=) is used here.', 'Single-bit errors in data-link frames.',
    'Use the delimiter = to separate fields.'])
def test_ordinary_prose_is_not_forced_to_match_verbatim(text):
    source = chunk(content='MAC addresses are used in frame headers to identify source',
                   warnings=['suspicious_formula_layout'])
    assert not unsafe_symbolic_content(text, [source])


def test_complete_equation_requires_reliable_expression_not_just_matching_operator():
    assert unsafe_symbolic_content('A ⊕ B', [chunk(content='C ⊕ D')])
    assert unsafe_symbolic_content('x^2', [chunk(content='x2')])
    assert not unsafe_symbolic_content('x = 2', [chunk(content='x=2')])


def test_formula_array_cannot_use_unreadable_source_even_without_layout_warning():
    data = payload()
    data['formulas'] = [dict(source_chunk_ids=[1], source_page=1, formula='x=2',
                             reliable=True, explanation=None)]
    result = ai(FakeProvider([data])).extract([chunk(content='x=2; \uf0c5')])
    assert result.knowledge.formulas == [] and result.formulas_omitted == 1


def test_masking_database_copy_never_mutates_persisted_source_or_knowledge(db, prepared):
    service, resource = prepared
    service.generate(db, resource.id, ai(FakeProvider()))
    before = json.dumps(db.get(ResourceKnowledge, resource.id).payload, sort_keys=True)
    row = db.scalar(select(DocumentChunk).where(DocumentChunk.resource_id == resource.id))
    row.content = 'MAC addresses identify the source. \uf0c5'
    db.commit()
    original = (row.id, row.page_number, row.chunk_index, row.content)
    inputs = [chunk(row.page_number, row.content).model_copy(update={
        'source_chunk_id': row.id, 'resource_id': row.resource_id, 'chunk_index': row.chunk_index})]
    safe, _ = prepare_ai_chunks(inputs)
    assert UNREADABLE_SYMBOL in safe[0].content
    db.expire_all()
    row = db.get(DocumentChunk, original[0])
    assert (row.id, row.page_number, row.chunk_index, row.content) == original
    assert json.dumps(db.get(ResourceKnowledge, resource.id).payload, sort_keys=True) == before


@pytest.mark.parametrize('fixture', json.loads(
    (Path(__file__).parent / 'fixtures/symbolic_regressions.json').read_text(encoding='utf-8')),
    ids=['synthetic-unreadable-operator', 'synthetic-incomplete-equation'])
def test_symbolic_regressions_blocked_before_semantic_review(fixture):
    source = KnowledgeInput.model_validate(fixture['source'])
    data = dict(topic='', overview='', concepts=[], key_points=[], questions=[],
                formulas=[], exam_focus=[], examples=[fixture['example']])
    provider = FakeProvider([data])
    result = ai(provider).extract([source])
    assert result.knowledge.examples == []
    assert result.formula_filtered_counts['examples'] == 1
    assert provider.semantic_calls == []  # No unsafe surviving claim to assess.
