"""Creates runs and enforces one active run at a time (assumption A-1)."""
from __future__ import annotations

import shutil
import threading
from pathlib import Path

from app.core.run_store import RunStore
from app.core.settings import Settings
from app.core.workspace import Workspace, new_run_id


def safe_filename(name: str) -> str:
    cleaned = Path((name or "upload").replace("\\", "/")).name.strip()
    return (cleaned or "upload")[:200]


class RunService:
    def __init__(self, settings: Settings, store: RunStore, workspace: Workspace):
        self._settings = settings
        self._store = store
        self._workspace = workspace
        self._lock = threading.Lock()
        self._active = None

    @property
    def active_run_id(self):
        with self._lock:
            return self._active

    def try_acquire(self) -> bool:
        """Reserve the single run slot. Returns False if a run is already active."""
        with self._lock:
            if self._active is not None:
                return False
            self._active = "pending"
            return True

    def release(self, run_id=None) -> None:
        with self._lock:
            self._active = None

    def create_run(self, plugin, tmp_path: Path, original_filename: str) -> dict:
        """Move the checked upload into a new run folder and write run.json."""
        run_id = new_run_id()
        self._workspace.create_run_dirs(run_id)
        suffix = Path(safe_filename(original_filename)).suffix.lower() or ".bin"
        dest = self._workspace.input_dir(run_id) / f"input{suffix}"
        shutil.move(str(tmp_path), str(dest))
        record = self._store.create(
            run_id, plugin.manifest.id, safe_filename(original_filename), plugin.stage_names(self._settings)
        )
        with self._lock:
            self._active = run_id
        return record
