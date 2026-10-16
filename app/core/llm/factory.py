"""Build the configured provider. A new provider is one new class plus one line here."""
from __future__ import annotations

from app.core.errors import BlockerError
from app.core.llm.base import LlmPermanentError, LlmProvider


def _gemini(settings) -> LlmProvider:
    if not settings.gemini_api_key:
        raise BlockerError("GEMINI_API_KEY is not set. Add it to backend/.env and restart the server.")
    if not settings.gemini_model:
        raise BlockerError("GEMINI_MODEL is not set. Add the model name to backend/.env and restart the server.")
    from app.core.llm.gemini import GeminiProvider
    try:
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model, settings.llm_temperature)
    except LlmPermanentError as exc:
        raise BlockerError(str(exc)) from exc


def _mock(settings) -> LlmProvider:
    from app.core.llm.mock import MockProvider
    return MockProvider()


PROVIDERS = {"gemini": _gemini, "mock": _mock}


def create_provider(settings) -> LlmProvider:
    builder = PROVIDERS.get(settings.llm_provider)
    if builder is None:
        raise BlockerError(f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Available: {', '.join(PROVIDERS)}.")
    return builder(settings)
