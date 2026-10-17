"""The one interface every LLM provider implements. Nodes never talk to a provider directly (FR-LG1)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LlmResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LlmError(Exception):
    """Base class for LLM failures. The message is safe to show to the user."""


class LlmTransientError(LlmError):
    """Rate limit, server error or network problem. Worth retrying.

    retry_after: seconds the provider asked us to wait before the next try, when it said so."""

    def __init__(self, message: str = "", retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class LlmPermanentError(LlmError):
    """Bad key, unknown model, rejected request. Retrying cannot help."""


class LlmRequestTooLarge(LlmPermanentError):
    """This one request is larger than the provider accepts. Sending less (a smaller chunk) can help."""


class LlmSchemaError(LlmError):
    """The model kept returning JSON that failed validation, even after re-asking."""


class LlmProvider(ABC):
    name: str = "provider"
    model: str = ""
    temperature: float = 0.1
    # Tokens per minute the provider allows, when it tells us (0 = unknown). Used to pace calls.
    tokens_per_minute: int = 0

    @abstractmethod
    def generate(self, system: str, prompt: str, *, json_output: bool = True) -> LlmResult:
        """Send one request. Raise LlmTransientError or LlmPermanentError on failure."""
