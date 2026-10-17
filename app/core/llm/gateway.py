"""The model gateway (FR-LG1..LG5): delay between calls, retry with backoff, token budget,
tokens-per-minute pacing, JSON parsing with schema re-ask, and a log of every prompt and response."""
from __future__ import annotations

import json
import math
import random
import re
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from app.core.errors import BlockerError
from app.core.llm.base import LlmPermanentError, LlmProvider, LlmRequestTooLarge, LlmSchemaError, LlmTransientError

# Rough size of a request before sending it. Logged runs average 3.6 to 4 characters per token for
# VBA and English; 3.3 errs on the large side so a chunk that "fits" really does.
CHARS_PER_TOKEN = 3.3
# Output tokens to plan for before any reply has been seen.
DEFAULT_EXPECTED_OUTPUT = 1500
# Share of the per-minute limit one request's input may use, leaving room for its answer.
INPUT_SHARE_OF_TPM = 0.5
WINDOW_SECONDS = 60.0

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


def parse_json_text(text: str):
    """Parse model output as JSON. Tolerates a Markdown code fence around it."""
    text = (text or "").strip()
    match = _FENCE_RE.match(text)
    if match:
        text = match.group(1)
    return json.loads(text)


def estimate_tokens(*texts: str) -> int:
    return math.ceil(sum(len(t or "") for t in texts) / CHARS_PER_TOKEN)


class TokenWindow:
    """Tokens spent in the last minute, so calls can wait instead of running into a rate limit (429)."""

    def __init__(self):
        self.events: deque = deque()  # (time, tokens)
        self.output_seen: deque = deque(maxlen=20)

    def _drop_old(self, now: float) -> None:
        while self.events and now - self.events[0][0] >= WINDOW_SECONDS:
            self.events.popleft()

    def add(self, now: float, tokens: int, output_tokens: int) -> None:
        self.events.append((now, tokens))
        self.output_seen.append(output_tokens)

    def expected_output(self) -> int:
        if not self.output_seen:
            return DEFAULT_EXPECTED_OUTPUT
        return int(max(self.output_seen))

    def wait_for(self, now: float, need: int, limit: int) -> float:
        """Seconds to wait until `need` more tokens fit under `limit`."""
        self._drop_old(now)
        used = sum(t for _when, t in self.events)
        excess = used + min(need, limit) - limit
        if excess <= 0:
            return 0.0
        freed = 0
        for when, tokens in self.events:
            freed += tokens
            if freed >= excess:
                return max(0.0, when + WINDOW_SECONDS - now)
        return WINDOW_SECONDS


# One window per provider and model, shared by every stage, because the limit is per account.
_windows: dict = {}


def window_for(provider: LlmProvider) -> TokenWindow:
    return _windows.setdefault((provider.name, provider.model), TokenWindow())


class LlmGateway:
    def __init__(self, provider: LlmProvider, settings, log_dir: Path | None = None, tokens_before: int = 0,
                 sleep=time.sleep, clock=time.monotonic, rng=random.random, window: TokenWindow | None = None):
        self.provider = provider
        self.settings = settings
        self.window = window or window_for(provider)
        self.log_dir = Path(log_dir) if log_dir else None
        self.tokens_before = tokens_before
        self.tokens_used = 0
        self.calls = 0
        self._sleep = sleep
        self._clock = clock
        self._rng = rng
        self._last_call_end = None

    # ----- public -----
    def tokens_per_minute(self) -> int:
        """The configured limit, else the one the provider reported, else 0 (no pacing)."""
        return int(getattr(self.settings, "llm_tokens_per_minute", 0) or getattr(self.provider, "tokens_per_minute", 0) or 0)

    def max_input_tokens(self) -> int:
        """Largest input one request should have (0 = no limit)."""
        configured = int(getattr(self.settings, "llm_max_input_tokens", 0) or 0)
        if configured:
            return configured
        tpm = self.tokens_per_minute()
        return int(tpm * INPUT_SHARE_OF_TPM) if tpm else 0

    def fits(self, system: str, prompt: str) -> bool:
        """True when a request is small enough to send. Stages split a chunk that does not fit."""
        cap = self.max_input_tokens()
        return not cap or estimate_tokens(system, prompt) <= cap

    def call_json(self, node: str, system: str, prompt: str, validate):
        """Ask for JSON and check it with validate(data) -> list of error strings.

        On invalid JSON or a failed check the model is re-asked with the error, up to
        settings.schema_reask times. Raises LlmSchemaError if it never gets valid,
        LlmTransientError if retries run out, LlmPermanentError for a bad key or model,
        and BlockerError if the token budget is spent.
        """
        current = prompt
        last_problem = ""
        for attempt in range(self.settings.schema_reask + 1):
            text = self._call(node, system, current)
            try:
                data = parse_json_text(text)
            except (json.JSONDecodeError, ValueError) as exc:
                last_problem = f"The reply was not valid JSON: {exc}"
            else:
                errors = validate(data)
                if not errors:
                    return data
                last_problem = "; ".join(errors[:5])
            self._log(node, {"event": "schema_rejected", "attempt": attempt + 1, "problem": last_problem})
            current = (
                f"{prompt}\n\nYour previous reply was rejected: {last_problem}\n"
                "Reply again with corrected JSON only, no other text."
            )
        raise LlmSchemaError(f"The model did not return valid JSON after {self.settings.schema_reask + 1} tries: {last_problem}")

    # ----- internals -----
    def _call(self, node: str, system: str, prompt: str) -> str:
        retries = max(0, self.settings.llm_retries)
        estimate = estimate_tokens(system, prompt)
        tpm = self.tokens_per_minute()
        if tpm and estimate >= tpm:
            # Can never fit in one minute's allowance. Do not spend a call finding that out.
            raise LlmRequestTooLarge(f"The request (about {estimate:,} tokens) is larger than the provider's "
                                     f"limit of {tpm:,} tokens per minute.")
        for attempt in range(retries + 1):
            self._check_budget()
            self._wait_between_calls()
            self._wait_for_rate_limit(node, estimate)
            try:
                result = self.provider.generate(system, prompt)
            except LlmTransientError as exc:
                self._last_call_end = self._clock()
                self._log(node, {"event": "transient_error", "attempt": attempt + 1, "error": str(exc)})
                if attempt >= retries:
                    raise LlmTransientError(f"{exc} Gave up after {retries} retries.") from exc
                self._sleep(max(self._backoff(attempt), min(exc.retry_after or 0, WINDOW_SECONDS)))
                continue
            except LlmPermanentError as exc:
                self._log(node, {"event": "permanent_error", "attempt": attempt + 1, "error": str(exc)})
                raise
            self._last_call_end = self._clock()
            self.calls += 1
            self.tokens_used += result.total_tokens
            self.window.add(self._last_call_end, result.total_tokens or estimate, result.output_tokens)
            self._log(node, {
                "event": "call", "attempt": attempt + 1, "provider": self.provider.name,
                "model": self.provider.model, "temperature": self.provider.temperature,
                "system": system, "prompt": prompt, "response": result.text,
                "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
            })
            return result.text
        raise LlmTransientError("The model could not be reached.")  # not reachable, keeps type checkers calm

    def _check_budget(self) -> None:
        budget = self.settings.max_tokens_per_run
        if budget and self.tokens_before + self.tokens_used >= budget:
            raise BlockerError(
                f"The token budget for this run ({budget:,}) is used up. "
                "Raise MAX_TOKENS_PER_RUN or analyze a smaller workbook."
            )

    def _wait_between_calls(self) -> None:
        delay = self.settings.llm_call_delay_seconds
        if delay > 0 and self._last_call_end is not None:
            remaining = delay - (self._clock() - self._last_call_end)
            if remaining > 0:
                self._sleep(remaining)

    def _wait_for_rate_limit(self, node: str, estimate: int) -> None:
        tpm = self.tokens_per_minute()
        if not tpm:
            return
        wait = self.window.wait_for(self._clock(), estimate + self.window.expected_output(), tpm)
        if wait > 0:
            self._log(node, {"event": "rate_wait", "seconds": round(wait, 1), "tokens_per_minute": tpm})
            self._sleep(wait)

    def _backoff(self, attempt: int) -> float:
        base = self.settings.llm_backoff_base_seconds
        cap = self.settings.llm_backoff_max_seconds
        return min(cap, base * (2 ** attempt)) * (0.75 + 0.25 * self._rng())

    def _log(self, node: str, entry: dict) -> None:
        """One JSON line per event in logs/llm/{node}.jsonl. The API key is never part of an entry."""
        if self.log_dir is None:
            return
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
            with open(self.log_dir / f"{node}.jsonl", "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # logging must never break a run
