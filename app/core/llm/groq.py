"""Groq provider, using its OpenAI-compatible chat completions endpoint over httpx."""
from __future__ import annotations

import re

from app.core.llm.base import LlmPermanentError, LlmProvider, LlmRequestTooLarge, LlmResult, LlmTransientError

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_PERMANENT_HINTS = {
    400: "Groq rejected the request (400). Check GROQ_MODEL and the prompt size.",
    401: "Groq rejected the API key (401). Check GROQ_API_KEY in backend/.env.",
    403: "Groq refused access (403). Check that GROQ_API_KEY is valid for this model.",
    404: "Groq does not know the model (404). Check GROQ_MODEL in backend/.env.",
    413: "Groq rejected the request as too large (413).",
}
_LIMIT_RE = re.compile(r"\(TPM\):\s*Limit\s+(\d+)", re.IGNORECASE)
_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")

# Tokens-per-minute limit last reported by Groq, per model. Kept across provider instances so that
# every stage of a run (and the next run) starts out knowing it.
_learned_tpm: dict = {}


def _error_detail(body) -> tuple[str, str]:
    """Return (code, message) from a Groq error body, or empty strings."""
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        err = body["error"]
        return str(err.get("code") or ""), str(err.get("message") or "")
    return "", ""


def parse_duration(text) -> float | None:
    """Seconds from a Groq duration such as "7.66s", "2m59.56s", "120ms" or a plain number."""
    if text is None:
        return None
    text = str(text).strip()
    try:
        return float(text)
    except ValueError:
        pass
    parts = _DURATION_RE.findall(text)
    if not parts:
        return None
    scale = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}
    return sum(float(n) * scale[unit] for n, unit in parts)


def classify_status(status: int, body=None, retry_after: float | None = None):
    """Map an HTTP error status (and Groq error body) to a transient or permanent LlmError."""
    code, message = _error_detail(body)
    if status == 429:
        if "per day" in message.lower() or "(TPD)" in message or "(RPD)" in message:
            return LlmPermanentError(f"Groq daily limit reached (429). Try again later or upgrade the Groq plan. {message}".strip())
        return LlmTransientError("Groq rate limit reached (429).", retry_after=retry_after)
    if status in (408, 409) or status >= 500:
        return LlmTransientError(f"Groq server error ({status}).", retry_after=retry_after)
    if code == "json_validate_failed":
        # The model produced invalid JSON in JSON mode. A new attempt usually succeeds.
        return LlmTransientError("Groq could not produce valid JSON for this request.")
    if status == 413 or code == "rate_limit_exceeded":
        return LlmRequestTooLarge(f"{_PERMANENT_HINTS[413]} {message}".strip())
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


def default_reasoning_effort(model: str) -> str:
    """gpt-oss models think before answering. "low" keeps that short, which saves most of the output tokens."""
    return "low" if "gpt-oss" in (model or "").lower() else ""


class GroqProvider(LlmProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str, temperature: float = 0.1, reasoning_effort: str | None = None,
                 timeout: float = 180.0):
        try:
            import httpx
        except ImportError as exc:
            raise LlmPermanentError("The 'httpx' package is not installed (pip install httpx).") from exc
        self.model = model
        self.temperature = temperature
        effort = default_reasoning_effort(model) if reasoning_effort is None else reasoning_effort.strip().lower()
        self.reasoning_effort = "" if effort == "off" else effort
        self._client = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )

    @property
    def tokens_per_minute(self) -> int:
        return _learned_tpm.get(self.model, 0)

    def _learn_limits(self, headers, message: str = "") -> None:
        limit = headers.get("x-ratelimit-limit-tokens")
        match = _LIMIT_RE.search(message or "")
        value = limit or (match.group(1) if match else None)
        try:
            if value and int(value) > 0:
                _learned_tpm[self.model] = int(value)
        except ValueError:
            pass

    def generate(self, system: str, prompt: str, *, json_output: bool = True) -> LlmResult:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        if json_output:
            payload["response_format"] = {"type": "json_object"}
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        try:
            response = self._client.post(GROQ_URL, json=payload)
        except Exception as exc:
            raise classify_error(exc) from exc
        try:
            body = response.json()
        except ValueError:
            body = None
        self._learn_limits(response.headers, _error_detail(body)[1])
        if response.status_code >= 400:
            raise classify_status(response.status_code, body, parse_duration(response.headers.get("retry-after")))
        try:
            text = body["choices"][0]["message"].get("content")
        except (TypeError, KeyError, IndexError):
            raise LlmTransientError("Groq returned an answer in an unexpected format.")
        if not text:
            raise LlmTransientError("Groq returned an empty answer.")
        usage = body.get("usage") or {}
        return LlmResult(text=text, input_tokens=int(usage.get("prompt_tokens") or 0),
                         output_tokens=int(usage.get("completion_tokens") or 0))
