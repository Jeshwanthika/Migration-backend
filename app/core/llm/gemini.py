"""Google AI Studio (Gemini) provider, using the google-genai SDK."""
from __future__ import annotations

from app.core.llm.base import LlmPermanentError, LlmProvider, LlmResult, LlmTransientError

_PERMANENT_HINTS = {
    400: "Gemini rejected the request (400). Check GEMINI_MODEL and the prompt size.",
    401: "Gemini rejected the API key (401). Check GEMINI_API_KEY in backend/.env.",
    403: "Gemini refused access (403). Check that GEMINI_API_KEY is valid and the API is enabled for it.",
    404: "Gemini does not know the model (404). Check GEMINI_MODEL in backend/.env.",
}


def classify_error(exc: Exception):
    """Map an SDK or network exception to a transient or permanent LlmError."""
    code = getattr(exc, "code", None)
    if code is None:
        code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        if code == 429:
            return LlmTransientError("Gemini rate limit or quota reached (429).")
        if code in (408, 409) or code >= 500:
            return LlmTransientError(f"Gemini server error ({code}).")
        return LlmPermanentError(_PERMANENT_HINTS.get(code, f"Gemini returned an error ({code}): {exc}"))
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return LlmTransientError(f"Could not reach Gemini: {exc.__class__.__name__}")
    name = exc.__class__.__name__
    if any(part in name for part in ("Timeout", "Connect", "Transport", "Network")):
        return LlmTransientError(f"Could not reach Gemini: {name}")
    return LlmPermanentError(f"Unexpected Gemini error: {name}: {exc}")


class GeminiProvider(LlmProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, temperature: float = 0.1):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise LlmPermanentError("The 'google-genai' package is not installed (pip install google-genai).") from exc
        self.model = model
        self.temperature = temperature
        self._types = types
        self._client = genai.Client(api_key=api_key)

    def generate(self, system: str, prompt: str, *, json_output: bool = True) -> LlmResult:
        config = self._types.GenerateContentConfig(
            system_instruction=system,
            temperature=self.temperature,
            response_mime_type="application/json" if json_output else "text/plain",
        )
        try:
            response = self._client.models.generate_content(model=self.model, contents=prompt, config=config)
        except Exception as exc:
            raise classify_error(exc) from exc
        text = getattr(response, "text", None)
        if not text:
            raise LlmTransientError("Gemini returned an empty answer (it may have been blocked).")
        usage = getattr(response, "usage_metadata", None)
        input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0) + int(
            getattr(usage, "thoughts_token_count", 0) or 0)
        return LlmResult(text=text, input_tokens=input_tokens, output_tokens=output_tokens)
