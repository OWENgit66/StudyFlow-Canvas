"""DeepSeek Chat Completions JSON mode; strict validation remains in AIService."""
import json

import httpx2 as httpx

from app.core.config import Settings
from app.services.ai_errors import (
    AIConfigurationError, AIError, AIRefusalError, AIResponseError, AITransientError,
)


class DeepSeekProvider:
    name = "deepseek"

    def __init__(self, settings: Settings, *, transport=None):
        if (settings.llm_provider != self.name or not settings.llm_model.strip()
                or not settings.deepseek_api_key.get_secret_value().strip()):
            raise AIConfigurationError(
                "Configure LLM_PROVIDER=deepseek, LLM_MODEL and DEEPSEEK_API_KEY locally."
            )
        self.model = settings.llm_model
        self.settings = settings
        self.transport = transport
        # Safe per-attempt observability, including responses later rejected by AIService.
        self.request_usage: list[dict] = []

    def generate(self, system: str, user: str, schema: dict) -> str:
        usage_record = {'request': len(self.request_usage) + 1, 'model': self.model}
        self.request_usage.append(usage_record)
        instructions = (
            system + "\nReturn exactly one JSON object matching this JSON Schema. "
            "Do not wrap JSON in markdown. Include all required fields.\n"
            + json.dumps(schema, ensure_ascii=False)
        )
        try:
            with httpx.Client(timeout=self.settings.llm_timeout_seconds,
                              transport=self.transport, follow_redirects=False) as client:
                with client.stream(
                    "POST", "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": "Bearer " + self.settings.deepseek_api_key.get_secret_value()},
                    json={
                        "model": self.model,
                        "messages": [{"role": "system", "content": instructions},
                                     {"role": "user", "content": user}],
                        "response_format": {"type": "json_object"},
                        "max_tokens": self.settings.llm_max_output_tokens,
                        "thinking": {"type": "disabled"},
                        "stream": False,
                    },
                ) as response:
                    usage_record['http_status'] = response.status_code
                    if response.status_code in {408, 429} or response.status_code >= 500:
                        raise AITransientError("DeepSeek is temporarily unavailable or rate limited.")
                    if response.status_code in {401, 403}:
                        raise AIConfigurationError("DeepSeek authentication or access failed; check local configuration.")
                    if response.status_code != 200:
                        raise AIError("DeepSeek request rejected; check model and configuration.")
                    data = bytearray()
                    for part in response.iter_bytes():
                        data.extend(part)
                        if len(data) > 1000000:
                            raise AIResponseError("DeepSeek response exceeds the allowed size.")
            body = json.loads(data)
            usage = body.get('usage', {})
            if isinstance(usage, dict):
                usage_record.update({key: usage[key] for key in (
                    'prompt_tokens', 'completion_tokens', 'total_tokens',
                    'prompt_cache_hit_tokens', 'prompt_cache_miss_tokens'
                ) if type(usage.get(key)) is int and usage[key] >= 0})
            choices = body.get("choices")
            if not isinstance(choices, list) or len(choices) != 1:
                raise AIResponseError("DeepSeek did not return one completion.")
            choice = choices[0]
            message = choice.get("message", {})
            if message.get("refusal") or choice.get("finish_reason") == "content_filter":
                raise AIRefusalError("DeepSeek declined this extraction.")
            if choice.get("finish_reason") != "stop":
                raise AIResponseError("DeepSeek response was incomplete.")
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise AIResponseError("DeepSeek returned empty content.")
            # Do not repair JSON or use reasoning_content as a fallback.
            # AIService validates the full schema and source evidence, and owns bounded retries.
            return content
        except (httpx.HTTPError, httpx.InvalidURL):
            raise AITransientError("DeepSeek connection failed or timed out.") from None
        except (ValueError, TypeError, KeyError, AttributeError):
            raise AIResponseError("DeepSeek returned an invalid response envelope.") from None
