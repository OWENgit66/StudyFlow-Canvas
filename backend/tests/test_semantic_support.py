import json

import pytest
from sqlalchemy import select, func

from app.core.config import Settings
from app.models import Concept, ResourceKnowledge, DocumentChunk
from app.schemas.semantic import SemanticReview
from app.services.ai_errors import AIResponseError, AITransientError, KnowledgeInputError
from app.services.ai_service import validate_grounding
from app.schemas.knowledge import KnowledgeOutput
from app.services.semantic_support import SemanticSupportService, SEMANTIC_PROMPT
from test_knowledge import payload, chunk, ai, FakeProvider, prepared
from semantic_helpers import semantic_response


@pytest.mark.parametrize('claim', ['Parity detects single-bit errors.',
                                 'Parity can be used to detect single-bit errors.'])
def test_exact_and_paraphrased_supported_claims_retained(claim):
    data = payload();data['concepts'][0].update(name='Parity', definition=claim)
    provider = FakeProvider([data], semantic_judge=lambda c,s: True)
    result = ai(provider).extract([chunk(content='Parity detects single-bit errors.')])
    assert result.knowledge.concepts[0].definition == claim
    assert result.knowledge.concepts[0].semantic_support['definition'].supported
    assert result.request_counts == {'generation':1, 'semantic_validation':1}
    assert provider.semantic_calls


@pytest.mark.parametrize('claim', ['Parity detects and corrects all errors.',
                                 'The fictional ExampleNet was an important milestone.',
                                 'The example proves a universal odd-and-even parity rule.'])
def test_broad_or_unsupported_significance_claim_rejected(claim):
    data = payload();data['key_points'][0]['content'] = claim
    provider = FakeProvider([data], semantic_judge=lambda c,s: c['text'] != claim)
    result = ai(provider).extract([chunk()])
    assert result.knowledge.key_points == []
    assert result.semantic_review.rejected == 1
    assert len(result.knowledge.concepts) == 1
    assert claim not in result.knowledge.model_dump_json()
    rejection = next(d for d in result.semantic_review.decisions if not d.supported)
    assert rejection.unsupported_parts == [claim]


def test_explanation_removed_definition_retained():
    data = payload();data['concepts'][0]['explanation'] = 'An important milestone.'
    result = ai(FakeProvider([data], semantic_judge=lambda c,s: c['field'] != 'explanation')).extract([chunk()])
    item = result.knowledge.concepts[0]
    assert item.definition == 'Carries data' and item.explanation == ''
    assert set(item.semantic_support) == {'name', 'definition'}
    assert result.semantic_review.partially_reduced == 1


def test_unsupported_name_drops_entire_concept():
    result = ai(FakeProvider([payload()], semantic_judge=lambda c,s: c['field'] != 'name')).extract([chunk()])
    assert not result.knowledge.concepts
    assert result.semantic_review.rejected == 1


@pytest.mark.parametrize('complete', [True, False])
def test_multi_source_citation_completeness(complete):
    data = payload();item=data['key_points'][0]
    item['content'] = 'Categories are partitioning and random access; TDMA is partitioning.'
    if complete:
        item.update(source_chunk_ids=[1,2], source_pages=[1,2])
    seen=[]
    def judge(claim,sources):
        if claim['claim_id'].startswith('key_points'):
            seen.append(sources)
            return any('TDMA' in s['text'] for s in sources)
        return True
    result = ai(FakeProvider([data],semantic_judge=judge)).extract([
        chunk(content='Categories: partitioning and random access.'),
        chunk(2, 'TDMA is partitioning.')])
    assert bool(result.knowledge.key_points) is complete
    assert {s['source_chunk_id'] for s in seen[0]} == ({1,2} if complete else {1})


def test_reviewer_never_receives_uncited_material_or_model_debug_evidence():
    data=payload(quote='Fabricated quote with a credential-like string.')
    provider=FakeProvider([data])
    ai(provider).extract([chunk(),chunk(2,'UNRELATED COURSE CONTENT')])
    encoded='\n'.join(call[1] for call in provider.semantic_calls)
    assert 'UNRELATED COURSE CONTENT' not in encoded
    assert 'Fabricated quote' not in encoded
    assert 'Frames carry data.' in encoded
    assert all('only' in call[0].lower() for call in provider.semantic_calls)


@pytest.mark.parametrize('kind', ['missing', 'duplicate', 'invented', 'contradiction', 'malformed'])
def test_incomplete_or_invalid_review_is_processing_failure(kind):
    class InvalidReview(FakeProvider):
        def generate(self, system,user,schema):
            if schema.get('title') != 'SemanticReview':return super().generate(system,user,schema)
            body=json.loads(semantic_response(user))
            if kind=='missing':body['decisions'].pop()
            if kind=='duplicate':body['decisions'].append(body['decisions'][0])
            if kind=='invented':body['decisions'][0]['claim_id']='invented'
            if kind=='contradiction':body['decisions'][0]['unsupported_parts']=['Not actually supported']
            if kind=='malformed':return 'not json'
            return json.dumps(body)
    with pytest.raises(AIResponseError):
        ai(InvalidReview(),llm_max_retries=0).extract([chunk()])


def test_review_retry_bounded_and_no_false_success():
    provider=FakeProvider(semantic_responses=[AITransientError('safe')]*3)
    with pytest.raises(AITransientError):ai(provider,llm_max_retries=1).extract([chunk()])
    assert len(provider.semantic_calls)==2


def test_transient_review_failure_then_success():
    provider=FakeProvider(semantic_responses=[AITransientError('safe')])
    result=ai(provider).extract([chunk()])
    assert result.request_counts == {'generation':1,'semantic_validation':2}


def test_optional_filtered_content_persists_and_reprocessing_stays_atomic(db,prepared):
    service,resource=prepared
    stored=db.scalar(select(DocumentChunk).where(DocumentChunk.resource_id==resource.id))
    data=payload(chunk_id=stored.id)
    data['concepts'][0]['explanation']='An important milestone.'
    data['key_points'].append(dict(data['key_points'][0],content='Unsupported general rule.'))
    provider=FakeProvider([data],semantic_judge=lambda c,s: c['text'] not in {
        'An important milestone.','Unsupported general rule.'})
    saved=service.generate(db,resource.id,ai(provider))
    assert saved.extraction.semantic_review.rejected==1
    assert saved.extraction.semantic_review.partially_reduced==1
    assert db.scalar(select(func.count()).select_from(Concept))==1
    assert db.scalar(select(Concept)).explanation==''
    before=db.get(ResourceKnowledge,resource.id).payload
    with pytest.raises(AITransientError):
        service.generate(db,resource.id,ai(FakeProvider(semantic_responses=[AITransientError('safe')]),llm_max_retries=0))
    assert db.get(ResourceKnowledge,resource.id).payload==before


@pytest.mark.parametrize('category,field', [('questions','answer'),('examples','description'),
                                         ('formulas','explanation'),('exam_focus','content')])
def test_required_categories_are_reviewed(category,field):
    data=payload();source=chunk(content='Important: Frames carry data. x=2')
    common=dict(source_chunk_ids=[1],source_pages=[1])
    if category=='examples':data[category]=[dict(common,description='Unsupported')]
    elif category=='formulas':data[category]=[dict(source_chunk_ids=[1],source_page=1,formula='x=2',explanation='Unsupported',reliable=True)]
    elif category=='exam_focus':data[category]=[dict(common,content='Unsupported')]
    else:data[category][0][field]='Unsupported'
    result=ai(FakeProvider([data],semantic_judge=lambda c,s:c['text']!='Unsupported')).extract([source])
    if category=='formulas':
        assert result.knowledge.formulas[0].explanation is None
        assert result.semantic_review.partially_reduced==1
    else:assert getattr(result.knowledge,category)==[]


def test_summary_uses_only_reviewed_retained_text():
    data=payload();data['overview']='External unsupported textbook claim.';data['topic']='Major milestone'
    result=ai(FakeProvider([data])).extract([chunk()])
    assert result.knowledge.overview=='Frames carry data.'
    assert result.knowledge.topic=='Frame'


def test_semantic_schema_is_openai_strict_compatible():
    schema=SemanticReview.model_json_schema()
    for obj in [schema,*schema['$defs'].values()]:
        assert obj['additionalProperties'] is False
        assert set(obj['required'])==set(obj['properties'])
    assert 'verified fact' in SEMANTIC_PROMPT
    assert 'Ambiguous or partial support means supported=false' in SEMANTIC_PROMPT


def test_semantic_batches_are_bounded_and_do_not_truncate_sources():
    data=payload()
    data['key_points']=[dict(data['key_points'][0],content=f'Claim {i}') for i in range(60)]
    grounded,_=validate_grounding(KnowledgeOutput.model_validate(data),[chunk()])
    calls=[]
    def review(system,user,schema):
        calls.append(user)
        return semantic_response(user)
    result,summary=SemanticSupportService(review,Settings(_env_file=None,llm_batch_characters=2000)).review(grounded)
    assert len(calls)>1
    assert all(len(call)<=2000 for call in calls)
    assert len(result.key_points)==60
    assert all(source['text']=='Frames carry data.' for call in calls
               for group in json.loads(call)['groups'] for source in group['sources'])


def test_oversized_semantic_claim_is_omitted_without_truncation_or_call():
    data=payload();grounded,_=validate_grounding(KnowledgeOutput.model_validate(data),[chunk(content='x'*2000)])
    def fail(*args):raise AssertionError('No paid call allowed for oversized source')
    result,summary=SemanticSupportService(fail,Settings(_env_file=None,llm_batch_characters=1000)).review(grounded)
    assert not result.concepts and not result.key_points and not result.questions
    assert summary.rejected==3


def test_semantic_total_budget_checked_before_semantic_calls():
    data=payload();data['key_points']=[dict(data['key_points'][0],content=f'Claim {i}') for i in range(60)]
    grounded,_=validate_grounding(KnowledgeOutput.model_validate(data),[chunk()])
    def fail(*args):raise AssertionError('No paid call allowed')
    with pytest.raises(KnowledgeInputError):
        SemanticSupportService(fail,Settings(_env_file=None,llm_max_batches=1)).review(grounded)
