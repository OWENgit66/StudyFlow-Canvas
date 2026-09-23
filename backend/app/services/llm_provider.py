"""Small provider boundary. HTTP uses the project's existing httpx2 dependency."""
from typing import Protocol
import httpx2 as httpx

from app.core.config import Settings
from app.services.ai_errors import AIConfigurationError, AIError, AITransientError, AIResponseError, AIRefusalError


class LLMProvider(Protocol):
    name: str
    model: str
    def generate(self, system: str, user: str, schema: dict) -> str: ...


class OpenAIProvider:
    name = 'openai'

    def __init__(self, settings: Settings, *, transport=None):
        if settings.llm_provider != 'openai' or not settings.llm_model.strip() or not settings.openai_api_key.get_secret_value().strip():
            raise AIConfigurationError('Configure LLM_PROVIDER=openai, LLM_MODEL and OPENAI_API_KEY locally.')
        self.model = settings.llm_model
        self.settings = settings
        self.transport = transport

    def generate(self, system: str, user: str, schema: dict) -> str:
        try:
            with httpx.Client(timeout=self.settings.llm_timeout_seconds, transport=self.transport,
                              follow_redirects=False) as client:
                with client.stream('POST', 'https://api.openai.com/v1/responses',
                    headers={'Authorization': 'Bearer ' + self.settings.openai_api_key.get_secret_value()},
                    json={'model':self.model, 'store':False, 'instructions':system,
                          'input':user, 'max_output_tokens':self.settings.llm_max_output_tokens,
                          'text':{'format':{'type':'json_schema','name':'studyflow_knowledge','strict':True,'schema':schema}}}) as response:
                    if response.status_code in {408,429} or response.status_code >= 500:
                        raise AITransientError('LLM timed out, is rate limited or unavailable; retry later.')
                    if response.status_code in {401,403}:
                        raise AIConfigurationError('LLM authentication or access failed; check local configuration.')
                    if response.status_code != 200:
                        raise AIError('LLM request rejected; check model and structured-output support.')
                    data = bytearray()
                    for part in response.iter_bytes():
                        data.extend(part)
                        if len(data) > 1000000:
                            raise AIResponseError('LLM response exceeds the allowed size.')
            import json
            body = json.loads(data)
            if not isinstance(body,dict) or body.get('status') != 'completed':
                raise AIResponseError('LLM response was incomplete.')
            texts = []
            for output in body.get('output',[]):
                if output.get('type') != 'message':
                    continue
                for content in output.get('content',[]):
                    if content.get('type') == 'refusal':
                        raise AIRefusalError('LLM declined this extraction.')
                    if content.get('type') == 'output_text':
                        texts.append(content['text'])
            if len(texts) != 1 or not isinstance(texts[0],str):
                raise AIResponseError('LLM did not return one structured result.')
            return texts[0]
        except (httpx.HTTPError, httpx.InvalidURL):
            raise AITransientError('LLM connection failed or timed out.') from None
        except (ValueError, TypeError, KeyError, AttributeError):
            raise AIResponseError('LLM returned an invalid response envelope.') from None
