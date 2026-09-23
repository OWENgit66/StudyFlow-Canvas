import json

import httpx2 as httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.services.ai_errors import AIConfigurationError, AIError, AIResponseError, AITransientError
from app.services.ai_service import AIService
from app.services.deepseek_provider import DeepSeekProvider
from app.services.llm_factory import create_llm_provider
from app.services.llm_provider import OpenAIProvider
from app.api.knowledge import get_ai_service
from test_knowledge import payload, chunk
from semantic_helpers import semantic_http_response


def settings(**overrides):
    values = dict(_env_file=None, llm_provider='deepseek', llm_model='deepseek-flash',
                  deepseek_api_key='fake-deepseek-test-key', openai_api_key='fake-openai-test-key',
                  knowledge_output_language='', llm_max_retries=1)
    values.update(overrides)
    return Settings(**values)


def envelope(content=None):
    return {'choices': [{'finish_reason': 'stop', 'message': {
        'content': json.dumps(payload()) if content is None else content}}]}


def service(handler, **overrides):
    config = settings(**overrides)
    provider = create_llm_provider(config, transport=httpx.MockTransport(lambda r:semantic_http_response(r) or handler(r)))
    return AIService(provider, config, sleep=lambda _: None)


@pytest.mark.parametrize('name,cls', [('openai', OpenAIProvider), ('deepseek', DeepSeekProvider)])
def test_provider_selection(name, cls):
    provider = create_llm_provider(settings(llm_provider=name))
    assert isinstance(provider, cls)
    assert provider.model == 'deepseek-flash'  # Factory never rewrites model identifiers.


@pytest.mark.parametrize('name', ['', 'unsupported'])
def test_unsupported_provider(name):
    with pytest.raises(AIConfigurationError):
        create_llm_provider(settings(llm_provider=name))


@pytest.mark.parametrize('overrides', [{'deepseek_api_key': ''}, {'llm_model': ''}])
def test_missing_deepseek_configuration(overrides):
    with pytest.raises(AIConfigurationError):
        create_llm_provider(settings(**overrides))


def test_deepseek_settings_from_environment(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fake-env-key')
    config = Settings(_env_file=None)
    assert isinstance(config.deepseek_api_key, SecretStr)
    assert config.deepseek_api_key.get_secret_value() == 'fake-env-key'
    assert 'fake-env-key' not in repr(config)


def test_api_dependency_uses_factory(monkeypatch):
    monkeypatch.setattr('app.api.knowledge.Settings', lambda: settings())
    assert isinstance(get_ai_service().provider, DeepSeekProvider)


def test_request_contract_and_success():
    def handler(request):
        assert str(request.url) == 'https://api.deepseek.com/chat/completions'
        assert request.method == 'POST'
        assert request.headers['Authorization'] == 'Bearer fake-deepseek-test-key'
        body = json.loads(request.content)
        assert body['model'] == 'deepseek-flash'
        assert body['response_format'] == {'type': 'json_object'}
        assert body['max_tokens'] == 6000
        assert body['thinking'] == {'type': 'disabled'}
        assert body['stream'] is False
        prompt = body['messages'][0]['content']
        assert 'JSON Schema' in prompt and 'source_pages' in prompt and 'source_chunk_ids' in prompt
        assert body['messages'][1]['role'] == 'user'
        assert 'fake-openai-test-key' not in request.content.decode()
        return httpx.Response(200, json=envelope())
    result = service(handler).extract([chunk()])
    assert result.knowledge.concepts[0].source_pages == [1]


@pytest.mark.parametrize('content', ['', '  ', None, 12])
def test_empty_and_invalid_content_retries_are_bounded(content):
    calls = []
    def handler(request):
        calls.append(request)
        body = envelope('')
        body['choices'][0]['message'] = {'content': content, 'reasoning_content': json.dumps(payload())}
        return httpx.Response(200, json=body)
    with pytest.raises(AIResponseError):
        service(handler).extract([chunk()])
    assert len(calls) == 2


def test_empty_then_success():
    responses = iter([envelope(''), envelope()])
    assert service(lambda r: httpx.Response(200, json=next(responses))).extract([chunk()]).knowledge.topic == 'Frame'


@pytest.mark.parametrize('content', ['not json', '{}', '{"topic": 12}'])
def test_json_and_schema_validation(content):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=envelope(content))
    with pytest.raises(AIResponseError):
        service(handler).extract([chunk()])
    assert len(calls) == 2


@pytest.mark.parametrize('status,exception,attempts', [(429, AITransientError, 2), (500, AITransientError, 2),
    (401, AIConfigurationError, 1), (403, AIConfigurationError, 1), (302, AIError, 1)])
def test_safe_http_errors(status, exception, attempts, caplog):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text='private-body fake-deepseek-test-key')
    with pytest.raises(exception) as exc:
        service(handler).extract([chunk()])
    assert len(calls) == attempts
    assert 'fake-deepseek-test-key' not in str(exc.value) + caplog.text
    assert 'private-body' not in str(exc.value) + caplog.text


def test_timeout_bounded():
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('private request details')
    with pytest.raises(AITransientError):
        service(handler).extract([chunk()])
    assert len(calls) == 2


@pytest.mark.parametrize('body', [{}, {'choices': []}, {'choices': [None]},
    {'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]}])
def test_malformed_or_incomplete_envelope(body):
    with pytest.raises(AIResponseError):
        service(lambda r: httpx.Response(200, json=body)).extract([chunk()])


def test_hallucinated_page_still_rejected():
    data = payload(999)
    with pytest.raises(AIResponseError):
        service(lambda r: httpx.Response(200, json=envelope(json.dumps(data)))).extract([chunk()])


def test_formula_safeguard_still_applies():
    data = payload(41, '(1-p)2(N-1)')
    data['formulas'] = [{'formula': '(1-p)^(2(N-1))', 'explanation': None, 'source_page': 41, 'source_chunk_ids': [41], 'reliable': True}]
    result = service(lambda r: httpx.Response(200, json=envelope(json.dumps(data)))).extract([
        chunk(41, '(1-p)2(N-1)', ['suspicious_formula_layout'])])
    assert result.formulas_omitted == 1
    assert not result.knowledge.formulas


def test_language_preference_preserves_evidence_instruction():
    def handler(request):
        prompt = json.loads(request.content)['messages'][0]['content']
        assert 'Chinese' in prompt and 'source IDs, pages and verbatim formulas unchanged' in prompt
        return httpx.Response(200, json=envelope())
    service(handler, knowledge_output_language='Chinese').extract([chunk()])


def test_openai_factory_keeps_responses_contract():
    def handler(request):
        assert str(request.url) == 'https://api.openai.com/v1/responses'
        assert request.headers['Authorization'] == 'Bearer fake-openai-test-key'
        body = json.loads(request.content)
        assert body['model'] == 'configured-openai-model'
        assert body['text']['format']['strict'] is True
        assert 'response_format' not in body
        return httpx.Response(200, json={'status': 'completed', 'output': [
            {'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(payload())}]}]})
    assert service(handler, llm_provider='openai', llm_model='configured-openai-model').extract([chunk()]).knowledge.topic == 'Frame'
