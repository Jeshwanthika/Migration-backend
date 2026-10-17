"""Groq provider, using its OpenAI-compatible chat completions endpoint over httpx."""
from __future__ import annotations

from app.core.llm.base import LlmPermanentError, LlmProvider, LlmResult, LlmTransientError

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_PERMANENT_HINTS = {
    400: "Groq rejected the request (400). Check GROQ_MODEL and the prompt size.",
    401: "Groq rejected the API key (401). Check GROQ_API_KEY in backend/.env.",
    403: "Groq refused access (403). Check that GROQ_API_KEY is valid for this model.",
    404: "Groq does not know the model (404). Check GROQ_MODEL in backend/.env.",
    413: "Groq rejected the request as too large (413). Lower CHUNK_MAX_CHARS in backend/.env.",
}


def _error_detail(body) -> tuple[str, str]:
    """Return (code, message) from a Groq error body, or empty strings."""
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        err = body["error"]
        return str(err.get("code") or ""), str(err.get("message") or "")
    return "", ""


def classify_status(status: int, body=None):
    """Map an HTTP error status (and Groq error body) to a transient or permanent LlmError."""
    code, message = _error_detail(body)
    if status == 429:
        return LlmTransientError("Groq rate limit or quota reached (429).")
    if status in (408, 409) or status >= 500:
        return LlmTransientError(f"Groq server error ({status}).")
    if code == "json_validate_failed":
        # The model produced invalid JSON in JSON mode. A new attempt usually succeeds.
        return LlmTransientError("Groq could not produce valid JSON for this request.")
    hint = _PERMANENT_HINTS.get(status, f"Groq returned an error ({status})")
    return LlmPermanentError(f"{hint} {message}".strip() if message and status not in (401, 403) else hint)


def classify_error(exc: Exception):
    """Map a network exception to a transient or permanent LlmError."""
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return LlmTransientError(f"Could not reach Groq: {exc.__class__.__name__}")
    name = exc.__class__.__name__
    if any(part in name for part in ("Timeout", "Connect", "Transport", "Network", "Protocol")):
        return LlmTransientError(f"Could not reach Groq: {name}")
    return LlmPermanentError(f"Unexpected Groq error: {name}: {exc}")


class GroqProvider(LlmProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str, temperature: float = 0.1, timeout: float = 180.0):
        try:
            import httpx
        except ImportError as exc:
            raise LlmPermanentError("The 'httpx' package is not installed (pip install httpx).") from exc
        self.model = model
        self.temperature = temperature
        self._client = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )

    def generate(self, system: str, prompt: str, *, json_output: bool = True) -> LlmResult:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        if json_output:
            payload["response_format"] = {"type": "json_object"}
        try:
            response = self._client.post(GROQ_URL, json=payload)
        except Exception as exc:
            raise classify_error(exc) from exc
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code >= 400:
            raise classify_status(response.status_code, body)
        try:
            text = body["choices"][0]["message"].get("content")
        except (TypeError, KeyError, IndexError):
            raise LlmTransientError("Groq returned an answer in an unexpected format.")
        if not text:
            raise LlmTransientError("Groq returned an empty answer.")
        usage = body.get("usage") or {}
        return LlmResult(text=text, input_tokens=int(usage.get("prompt_tokens") or 0),
                         output_tokens=int(usage.get("completion_tokens") or 0))
