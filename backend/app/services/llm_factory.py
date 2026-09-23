"""Explicit provider selection without credential or model fallback."""
from app.core.config import Settings
from app.services.ai_errors import AIConfigurationError
from app.services.llm_provider import LLMProvider, OpenAIProvider
from app.services.deepseek_provider import DeepSeekProvider


def create_llm_provider(settings: Settings, *, transport=None) -> LLMProvider:
    providers = {"openai": OpenAIProvider, "deepseek": DeepSeekProvider}
    provider = providers.get(settings.llm_provider)
    if provider is None:
        raise AIConfigurationError("Set LLM_PROVIDER to openai or deepseek.")
    return provider(settings, transport=transport)
