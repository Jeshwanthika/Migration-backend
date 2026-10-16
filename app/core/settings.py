"""All settings come from environment variables, optionally loaded from a .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer, got {raw!r}") from exc


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be a number, got {raw!r}") from exc


def _list(name: str, default: tuple) -> tuple:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def load_env_file() -> None:
    """Load backend/.env if python-dotenv is installed. The .env file is never packaged."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


@dataclass(frozen=True)
class Settings:
    workspace_root: Path
    max_upload_mb: int = 10
    max_vba_lines: int = 20000
    retention_days: int = 7
    enabled_stages: tuple = ("intake_check", "extractor", "analyzer", "spec_architect", "generator", "validator", "packager")
    cleanup_interval_seconds: int = 3600
    cors_origins: tuple = ("http://localhost:5173",)
    # Used from Phase 2 onward. Read now so configuration problems show up early.
    llm_provider: str = "gemini"
    gemini_model: str = ""
    gemini_api_key: str = field(default="", repr=False)
    llm_retries: int = 4
    llm_call_delay_seconds: float = 4.0
    llm_backoff_base_seconds: float = 2.0
    llm_backoff_max_seconds: float = 60.0
    llm_temperature: float = 0.1
    chunk_max_chars: int = 12000
    schema_reask: int = 2
    max_tokens_per_run: int = 0
    max_agent_steps: int = 25
    dotnet_timeout_sec: int = 300

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @classmethod
    def from_env(cls) -> "Settings":
        load_env_file()
        return cls(
            workspace_root=Path(os.environ.get("WORKSPACE_ROOT", "./workspace")),
            max_upload_mb=_int("MAX_UPLOAD_MB", 10),
            max_vba_lines=_int("MAX_VBA_LINES", 20000),
            retention_days=_int("RETENTION_DAYS", 7),
            enabled_stages=_list("ENABLED_STAGES", ("intake_check", "extractor", "analyzer", "spec_architect", "generator", "validator", "packager")),
            cleanup_interval_seconds=_int("CLEANUP_INTERVAL_SECONDS", 3600),
            cors_origins=_list("CORS_ORIGINS", ("http://localhost:5173",)),
            llm_provider=os.environ.get("LLM_PROVIDER", "gemini"),
            gemini_model=os.environ.get("GEMINI_MODEL", ""),
            gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
            llm_retries=_int("LLM_RETRIES", 4),
            llm_call_delay_seconds=_float("LLM_CALL_DELAY_SECONDS", 4.0),
            llm_backoff_base_seconds=_float("LLM_BACKOFF_BASE_SECONDS", 2.0),
            llm_backoff_max_seconds=_float("LLM_BACKOFF_MAX_SECONDS", 60.0),
            llm_temperature=_float("LLM_TEMPERATURE", 0.1),
            chunk_max_chars=_int("CHUNK_MAX_CHARS", 12000),
            schema_reask=_int("SCHEMA_REASK", 2),
            max_tokens_per_run=_int("MAX_TOKENS_PER_RUN", 0),
            max_agent_steps=_int("MAX_AGENT_STEPS", 25),
            dotnet_timeout_sec=_int("DOTNET_TIMEOUT_SEC", 300),
        )
