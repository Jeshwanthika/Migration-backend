"""Structured JSON logs per run (spec 5.2). The API key is never logged."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="seconds"),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def get_run_logger(logs_dir: Path, run_id: str) -> logging.Logger:
    logger = logging.getLogger(f"run.{run_id}")
    if not any(getattr(h, "_run_log", False) for h in logger.handlers):
        Path(logs_dir).mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(Path(logs_dir) / "run.log", encoding="utf-8")
        handler.setFormatter(JsonFormatter())
        handler._run_log = True  # marker so the handler is added only once
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
