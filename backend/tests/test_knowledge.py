import json
from types import SimpleNamespace
import httpx2 as httpx
import pymupdf
import pytest
from sqlalchemy import select,func
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.models import Resource,ResourceKnowledge,Concept,Question,Summary,DocumentChunk
from app.schemas.knowledge import KnowledgeInput,KnowledgeOutput
from app.services.ai_errors import (AIError,AIConfigurationError,AITransientError,AIResponseError,AIRefusalError,KnowledgeInputError,KnowledgeDatabaseError,KnowledgeNotFoundError)
from app.services.ai_service import AIService,make_batches,encode_batch,validate_grounding
from app.services.llm_provider import OpenAIProvider
from app.services.knowledge_service import KnowledgeService
from app.services.document_service import DocumentService
from app.services.document_processing import process_resource
from app.api.knowledge import get_ai_service,get_knowledge_service
from semantic_helpers import semantic_response, semantic_http_response


def payload(page=1,quote='Frames carry data.',chunk_id=None):
    evidence=[{'page_number':page,'quote':quote}]
    source={'source_chunk_ids':[chunk_id or page],'source_pages':[page],'evidence':evidence}
    return {'topic':'Frames','overview':'Frames carry data.',
            'concepts':[dict(source,name='Frame',definition='Carries data',explanation='',importance='medium')],
            'key_points':[dict(source,content='Frames carry data.')], 'formulas':[], 'examples':[], 'exam_focus':[],
            'questions':[dict(source,question='What carries data?',answer='Frames.')]}


def chunk(page=1,content='Frames carry data.',warnings=None,index=0):
    return KnowledgeInput(resource_id=1,source_chunk_id=page,page_number=page,chunk_index=index,content=content,warnings=warnings or [])


class FakeProvider:
    name='test'
    model='deterministic-fixture'
    def __init__(self,responses=None, *, semantic_judge=None, semantic_responses=None):
        self.responses=list(responses or [])
        self.calls=[]
        self.semantic_calls=[]
        self.semantic_judge=semantic_judge
        self.semantic_responses=list(semantic_responses or [])
    def generate(self,system,user,schema):
        if schema.get('title') == 'SemanticReview':
            self.semantic_calls.append((system,user,schema))
            if self.semantic_responses:
                response=self.semantic_responses.pop(0)
                if isinstance(response,Exception):raise response
                return response if isinstance(response,str) else json.dumps(response)
            return semantic_response(user,self.semantic_judge)
        self.calls.append((system,user,schema))
        if self.responses:
            response=self.responses.pop(0)
            if isinstance(response,Exception):raise response
            return response if isinstance(response,str) else json.dumps(response)
        c=json.loads(user)['chunks'][0]
        return json.dumps(payload(c['page_number'],c['content'],c['source_chunk_id']))


def ai(provider,**kwargs):
    return AIService(provider,Settings(_env_file=None,**kwargs),sleep=lambda _:None)


def test_grounded_output_and_no_spans_in_prompt():
    provider=FakeProvider()
    result=ai(provider).extract([chunk()])
    assert result.knowledge.concepts[0].source_pages == [1]
    system,user,schema=provider.calls[0]
    assert 'Never reconstruct damaged formulas' in system
    assert 'untrusted' in system
    assert set(json.loads(user)['chunks'][0]) == {'resource_id','source_chunk_id','page_number','chunk_index','content','warnings','label'}
    assert schema['additionalProperties'] is False
    assert set(schema['required']) == set(schema['properties'])


@pytest.mark.parametrize('code',['suspicious_formula_layout','unusual_symbol_position','encoding_warning'])
def test_damaged_formula_is_dropped_even_when_provider_repairs_it(code):
    data=payload(41,'(1-p)2(N-1)')
    data['formulas']=[{'formula':'(1-p)^(2(N-1))','source_page':41,'source_chunk_ids':[41],'explanation':'guessed','reliable':True}]
    provider=FakeProvider([data])
    result=ai(provider).extract([chunk(41,'(1-p)2(N-1)',[code])])
    assert result.knowledge.formulas == []
    assert result.formulas_omitted == 1
    assert code in provider.calls[0][1]
    assert result.warnings


def test_normal_formula_exact_text_allowed():
    text='EF = ES + Duration'
    data=payload(20,text)
    data['formulas']=[{'formula':text,'source_page':20,'source_chunk_ids':[20],'explanation':None,'reliable':True}]
    result=ai(FakeProvider([data])).extract([chunk(20,text)])
    assert result.knowledge.formulas[0].formula == text


@pytest.mark.parametrize('kind',['page','chunk','extra','type'])
def test_invalid_or_unsubstantiated_output_rejected(kind):
    data=payload()
    if kind=='page':data['concepts'][0]['source_pages']=[999]
    if kind=='chunk':data['concepts'][0]['source_chunk_ids']=[999]
    if kind=='extra':data['unknown']='not allowed'
    if kind=='type':data['concepts'][0]['source_pages']=['1']
    with pytest.raises(AIResponseError):ai(FakeProvider([data]),llm_max_retries=0).extract([chunk()])


def test_exam_focus_requires_explicit_quoted_cue():
    text='Learning outcome: identify frames.'
    data=payload(1,text)
    data['exam_focus']=[dict(data['key_points'][0],content='Learning outcome: identify frames.')]
    assert ai(FakeProvider([data])).extract([chunk(content=text)]).knowledge.exam_focus


def test_retry_json_failure_then_success():
    provider=FakeProvider(['not json',payload()])
    assert ai(provider).extract([chunk()]).batches == 1
    assert len(provider.calls)==2


def test_retry_is_bounded_and_no_partial_result():
    provider=FakeProvider([AITransientError('temporary')]*3)
    with pytest.raises(AITransientError):ai(provider,llm_max_retries=1).extract([chunk()])
    assert len(provider.calls)==2


def test_refusal_not_retried():
    provider=FakeProvider([AIRefusalError('refused')])
    with pytest.raises(AIRefusalError):ai(provider).extract([chunk()])
    assert len(provider.calls)==1


def test_batches_bound_json_and_preserve_all_text_and_sources():
    settings=Settings(_env_file=None,llm_batch_characters=1000)
    inputs=[chunk(page=1,content='中文"\\\n'*600),chunk(page=2,content='second page')]
    batches=make_batches(inputs,settings)
    assert len(batches)>1
    assert all(len(encode_batch(b))<=1000 for b in batches)
    assert ''.join(c.content for b in batches for c in b if c.page_number==1)==inputs[0].content
    assert {c.page_number for b in batches for c in b}=={1,2}


def test_batch_budget_checked_before_any_llm_call():
    provider=FakeProvider()
    with pytest.raises(KnowledgeInputError):
        ai(provider,llm_batch_characters=1000,llm_max_batches=1).extract([chunk(content='x'*5000)])
    assert not provider.calls


def test_citation_to_other_batch_is_rejected():
    provider=FakeProvider([payload(2)])
    with pytest.raises(AIResponseError):
        ai(provider,llm_batch_characters=1000,llm_max_retries=0).extract([chunk(content='Frames carry data.'+' '*850),chunk(2)])


def provider_with(handler):
    settings=Settings(_env_file=None,llm_provider='openai',llm_model='test-model',openai_api_key='test-secret')
    return OpenAIProvider(settings,transport=httpx.MockTransport(lambda r:semantic_http_response(r) or handler(r)))


def envelope(data=None,status='completed'):
    return {'status':status,'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(data or payload())}]}]}


def test_openai_request_contract_and_response():
    def handler(request):
        assert request.method=='POST' and str(request.url)=='https://api.openai.com/v1/responses'
        assert request.headers['Authorization']=='Bearer test-secret'
        body=json.loads(request.content)
        assert body['store'] is False
        assert body['text']['format']['strict'] is True
        assert body['text']['format']['type']=='json_schema'
        assert 'tools' not in body
        return httpx.Response(200,json=envelope())
    result=ai(provider_with(handler)).extract([chunk()])
    assert result.knowledge.topic=='Frame'


@pytest.mark.parametrize('status,error',[(401,AIConfigurationError),(403,AIConfigurationError),(429,AITransientError),(500,AITransientError),(400,AIError),(302,AIError)])
def test_provider_safe_http_errors(status,error,caplog):
    provider=provider_with(lambda request:httpx.Response(status,text='test-secret private prompt'))
    with pytest.raises(error) as exc:provider.generate('s','u',{})
    assert 'test-secret' not in str(exc.value)+caplog.text
    assert 'private prompt' not in str(exc.value)+caplog.text


def test_provider_timeout():
    def handler(request):raise httpx.ReadTimeout('private data')
    with pytest.raises(AITransientError):provider_with(handler).generate('s','u',{})


@pytest.mark.parametrize('body',[envelope(status='incomplete'),{'status':'completed','output':[]},{'status':'completed','output':None}])
def test_invalid_provider_envelope(body):
    with pytest.raises(AIResponseError):provider_with(lambda r:httpx.Response(200,json=body)).generate('s','u',{})


def test_provider_refusal():
    body={'status':'completed','output':[{'type':'message','content':[{'type':'refusal','refusal':'private'}]}]}
    with pytest.raises(AIRefusalError):provider_with(lambda r:httpx.Response(200,json=body)).generate('s','u',{})


def test_missing_configuration():
    with pytest.raises(AIConfigurationError):OpenAIProvider(Settings(_env_file=None,llm_provider='',llm_model='',openai_api_key=''))


@pytest.fixture
def prepared(tmp_path,db,graph):
    path=tmp_path/'lecture.pdf'
    with pymupdf.open() as pdf:
        p=pdf.new_page();p.insert_text((50,100),'Frames carry data.')
        pdf.save(path)
    resource=graph[-1]
    resource.local_path=str(path)
    db.commit()
    documents=DocumentService(Settings(_env_file=None,materials_root=tmp_path))
    process_resource(db,resource.id,documents)
    return KnowledgeService(documents),resource


def test_knowledge_persistence_replacement_and_read(db,prepared):
    service,resource=prepared
    for _ in range(2):
        result=service.generate(db,resource.id,ai(FakeProvider()))
        assert not result.stale
        assert service.read(db,resource.id).extraction.knowledge.topic=='Frame'
    assert db.scalar(select(func.count()).select_from(ResourceKnowledge))==1
    assert db.scalar(select(func.count()).select_from(Concept))==1
    assert db.scalar(select(func.count()).select_from(Question))==1
    assert 'pages 1' in db.scalar(select(Summary)).key_points[0]
    assert resource.sync_status=='completed'


def test_failed_generation_keeps_previous_knowledge(db,prepared):
    service,resource=prepared
    before=service.generate(db,resource.id,ai(FakeProvider())).model_dump()
    with pytest.raises(AIResponseError):service.generate(db,resource.id,ai(FakeProvider(['bad']),llm_max_retries=0))
    assert service.read(db,resource.id).model_dump()==before


def test_database_failure_rolls_back_all_projections(db,prepared,monkeypatch):
    service,resource=prepared
    before=service.generate(db,resource.id,ai(FakeProvider())).model_dump()
    from app.services import knowledge_service
    original=knowledge_service.save_knowledge
    def fail(*args,**kwargs):
        original(*args,**kwargs)
        raise SQLAlchemyError('private DB failure')
    monkeypatch.setattr(knowledge_service,'save_knowledge',fail)
    data=payload();data['overview']='Updated overview'
    with pytest.raises(KnowledgeDatabaseError):service.generate(db,resource.id,ai(FakeProvider([data])))
    assert service.read(db,resource.id).model_dump()==before
    assert db.scalar(select(func.count()).select_from(Concept))==1


def test_stale_chunks_rejected_before_llm(db,prepared):
    service,resource=prepared
    stored=db.scalar(select(DocumentChunk))
    stored.content='stale'
    db.commit()
    provider=FakeProvider()
    with pytest.raises(KnowledgeInputError):service.generate(db,resource.id,ai(provider))
    assert not provider.calls


def test_source_changes_during_llm_are_rejected(db,prepared):
    service,resource=prepared
    provider=FakeProvider()
    original=provider.generate
    def changed(*args):
        c=db.scalar(select(DocumentChunk));c.content='changed';db.commit()
        return original(*args)
    provider.generate=changed
    with pytest.raises(KnowledgeInputError):service.generate(db,resource.id,ai(provider))
    assert db.get(ResourceKnowledge,resource.id) is None


def test_read_reports_stale_after_source_change(db,prepared):
    service,resource=prepared
    service.generate(db,resource.id,ai(FakeProvider()))
    db.scalar(select(DocumentChunk)).content='changed'
    db.commit()
    with pytest.raises(KnowledgeNotFoundError):
        service.read(db,resource.id)
    assert service.read(db,resource.id,include_stale=True).stale is True


def test_generate_and_read_api(client,db,prepared):
    service,resource=prepared
    client.app.dependency_overrides[get_ai_service]=lambda:ai(FakeProvider())
    client.app.dependency_overrides[get_knowledge_service]=lambda:service
    result=client.post(f'/api/resources/{resource.id}/knowledge')
    assert result.status_code==200
    assert result.json()['extraction']['knowledge']['concepts'][0]['source_pages']==[1]
    assert client.get(f'/api/resources/{resource.id}/knowledge').status_code==200
    assert client.get('/api/resources/99999/knowledge').status_code==404
    assert client.get('/health').status_code==200


def test_multiple_resources_preserve_week_summary_and_other_concepts(db,prepared):
    service,first=prepared
    service.generate(db,first.id,ai(FakeProvider()))
    second=Resource(week_id=first.week_id,filename='other.pdf',file_type='pdf',local_path=first.local_path)
    db.add(second);db.commit()
    process_resource(db,second.id,service.documents)
    data=payload(chunk_id=db.scalar(select(DocumentChunk.id).where(DocumentChunk.resource_id==second.id)));data['overview']='Unreviewed overview';data['key_points'][0]['content']='Second resource overview'
    service.generate(db,second.id,ai(FakeProvider([data])))
    summary=db.scalar(select(Summary))
    assert f'Resource {first.id}:' in summary.overview
    assert f'Resource {second.id}:' in summary.overview
    assert db.scalar(select(func.count()).select_from(Concept))==2
    service.generate(db,first.id,ai(FakeProvider()))
    assert db.get(ResourceKnowledge,second.id).payload['knowledge']['overview']=='Second resource overview'
    assert db.scalar(select(func.count()).select_from(Concept))==2


def test_multiple_source_pages_preserved_in_canonical_payload(db,prepared):
    service,resource=prepared
    with pymupdf.open() as pdf:
        for _ in range(2):
            p=pdf.new_page();p.insert_text((50,100),'Frames carry data.')
        pdf.save(resource.local_path)
    process_resource(db,resource.id,service.documents)
    data=payload()
    ids=db.scalars(select(DocumentChunk.id).where(DocumentChunk.resource_id==resource.id).order_by(DocumentChunk.page_number)).all()
    data=payload(chunk_id=ids[0])
    data['concepts'][0]['source_chunk_ids']=ids
    data['concepts'][0]['source_pages']=[1,2]
    data['concepts'][0]['evidence']=data['concepts'][0]['evidence']+[{'page_number':2,'quote':'Frames carry data.'}]
    result=service.generate(db,resource.id,ai(FakeProvider([data])))
    assert result.extraction.knowledge.concepts[0].source_pages==[1,2]
    assert db.get(ResourceKnowledge,resource.id).payload['knowledge']['concepts'][0]['source_pages']==[1,2]


def test_real_pdf_formula_warnings_reach_ai_and_block_formulas(db,prepared):
    service,resource=prepared
    with pymupdf.open() as pdf:
        p=pdf.new_page();p.insert_text((50,100),'x',fontsize=20);p.insert_text((61,94),'2',fontsize=12)
        pdf.save(resource.local_path)
    process_resource(db,resource.id,service.documents)
    provider=FakeProvider()
    original=provider.generate
    def generate(system,user,schema):
        data=json.loads(original(system,user,schema))
        if schema.get('title') == 'SemanticReview':return json.dumps(data)
        data['formulas']=[{'formula':'x^2','source_page':1,'source_chunk_ids':data['concepts'][0]['source_chunk_ids'],'explanation':None,'reliable':True}]
        return json.dumps(data)
    provider.generate=generate
    result=service.generate(db,resource.id,ai(provider))
    assert result.extraction.formulas_omitted==1
    assert result.extraction.knowledge.formulas==[]
    assert 'suspicious_formula_layout' in provider.calls[0][1]


def test_knowledge_api_config_failure_does_not_expose_secret(client,monkeypatch):
    def missing():raise AIConfigurationError('LLM not configured.')
    client.app.dependency_overrides[get_ai_service]=missing
    result=client.post('/api/resources/1/knowledge')
    assert result.status_code==503
    assert result.json()['detail']['code']=='ai_not_configured'
    assert client.get('/health').status_code==200


def test_later_batch_failure_does_not_save_partial_knowledge(db,prepared):
    service,resource=prepared
    # Keep the baseline generated knowledge before simulating a long new source.
    before=service.generate(db,resource.id,ai(FakeProvider())).extraction.model_dump()
    with pymupdf.open() as pdf:
        for _ in range(3):
            p=pdf.new_page();p.insert_text((50,100),'Frames carry data.\n'*35,fontsize=11)
        pdf.save(resource.local_path)
    process_resource(db,resource.id,service.documents)
    provider=FakeProvider([payload(),AITransientError('unavailable')])
    with pytest.raises(AITransientError):service.generate(db,resource.id,ai(provider,llm_batch_characters=1000,llm_max_retries=0))
    assert db.get(ResourceKnowledge,resource.id).payload==before


def test_provider_response_size_limit():
    provider=provider_with(lambda r:httpx.Response(200,content=b'x'*1000001))
    with pytest.raises(AIResponseError):provider.generate('s','u',{})
