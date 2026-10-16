"""Run folder layout (section 5.3 of the spec) and retention cleanup."""
from __future__ import annotations

import re
import shutil
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.models import RUN_RUNNING, utc_now

ARTIFACT_FILES = {
    "vba_modules": "vba_modules.json",
    "analysis_model": "analysis_model.json",
    "migration_spec": "migration_spec.json",
    "generation_manifest": "generation_manifest.json",
    "validation_results": "validation_results.json",
}

_RUN_ID_RE = re.compile(r"^[a-f0-9]{32}$")


def is_valid_run_id(value) -> bool:
    return isinstance(value, str) and bool(_RUN_ID_RE.match(value))


def new_run_id() -> str:
    return uuid.uuid4().hex


class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id: str) -> Path:
        if not is_valid_run_id(run_id):
            raise ValueError("Invalid run id")
        return self.root / run_id

    def input_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "input"

    def artifacts_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "artifacts"

    def output_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "output"

    def logs_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "logs"

    def tmp_dir(self) -> Path:
        path = self.root / ".tmp"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create_run_dirs(self, run_id: str) -> Path:
        for sub in (self.input_dir, self.artifacts_dir, self.output_dir, self.logs_dir):
            sub(run_id).mkdir(parents=True, exist_ok=True)
        return self.run_dir(run_id)

    def artifact_path(self, run_id: str, name: str) -> Path:
        if name not in ARTIFACT_FILES:
            raise KeyError(name)
        return self.artifacts_dir(run_id) / ARTIFACT_FILES[name]

    def delete_run(self, run_id: str) -> None:
        shutil.rmtree(self.run_dir(run_id), ignore_errors=True)

    def cleanup_tmp(self, max_age_seconds: int = 3600) -> int:
        removed = 0
        cutoff = time.time() - max_age_seconds
        for item in self.tmp_dir().iterdir():
            try:
                if item.is_file() and item.stat().st_mtime < cutoff:
                    item.unlink()
                    removed += 1
            except OSError:
                continue
        return removed

    def cleanup_expired(self, store, retention_days: int, now: datetime | None = None, protected=()) -> list:
        """Delete runs older than the retention period. Running and protected runs are never deleted."""
        now = now or utc_now()
        cutoff = now - timedelta(days=retention_days)
        deleted = []
        for record in store.list_all():
            run_id = record.get("run_id")
            if run_id in protected or record.get("status") == RUN_RUNNING:
                continue
            stamp = record.get("finished_at") or record.get("started_at")
            try:
                when = datetime.fromisoformat(stamp)
            except (TypeError, ValueError):
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when < cutoff:
                self.delete_run(run_id)
                deleted.append(run_id)
        return deleted
