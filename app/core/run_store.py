"""The run record: one run.json file per run. No database (assumption A-2)."""
from __future__ import annotations

import json
import threading

from app.core.files import read_json, write_json_atomic
from app.core.models import (
    NODE_DONE, NODE_FAILED, NODE_PENDING, NODE_RUNNING, NODE_SKIPPED,
    RUN_FAILED, RUN_RUNNING, utc_now_iso,
)
from app.core.workspace import Workspace, is_valid_run_id


class RunStore:
    def __init__(self, workspace: Workspace):
        self._ws = workspace
        self._lock = threading.RLock()

    def _path(self, run_id):
        return self._ws.run_dir(run_id) / "run.json"

    def _write(self, run_id, record):
        write_json_atomic(self._path(run_id), record)

    def create(self, run_id, skill_id, filename, node_names) -> dict:
        record = {
            "run_id": run_id,
            "skill_id": skill_id,
            "filename": filename,
            "status": RUN_RUNNING,
            "current_node": None,
            "nodes": [
                {"name": n, "status": NODE_PENDING, "started_at": None, "finished_at": None}
                for n in node_names
            ],
            "tokens_used": 0,
            "detail": None,
            "flags_count": 0,
            "error": None,
            "started_at": utc_now_iso(),
            "finished_at": None,
        }
        with self._lock:
            self._write(run_id, record)
        return record

    def read(self, run_id):
        if not is_valid_run_id(run_id):
            return None
        path = self._path(run_id)
        if not path.is_file():
            return None
        try:
            return read_json(path)
        except (OSError, json.JSONDecodeError):
            return None

    def update(self, run_id, **fields) -> dict:
        with self._lock:
            record = self.read(run_id)
            if record is None:
                raise KeyError(run_id)
            record.update(fields)
            self._write(run_id, record)
            return record

    def set_node(self, run_id, name, status) -> dict:
        with self._lock:
            record = self.read(run_id)
            if record is None:
                raise KeyError(run_id)
            for node in record["nodes"]:
                if node["name"] == name:
                    node["status"] = status
                    if status == NODE_RUNNING:
                        node["started_at"] = utc_now_iso()
                    elif status in (NODE_DONE, NODE_FAILED):
                        node["finished_at"] = utc_now_iso()
            if status == NODE_RUNNING:
                record["current_node"] = name
            self._write(run_id, record)
            return record

    def add_progress(self, run_id, flags=0, tokens=0) -> dict:
        with self._lock:
            record = self.read(run_id)
            if record is None:
                raise KeyError(run_id)
            record["flags_count"] += flags
            record["tokens_used"] += tokens
            self._write(run_id, record)
            return record

    def finish(self, run_id, status, error=None) -> dict:
        with self._lock:
            record = self.read(run_id)
            if record is None:
                raise KeyError(run_id)
            record["status"] = status
            record["error"] = error
            record["finished_at"] = utc_now_iso()
            record["current_node"] = None
            if status == RUN_FAILED:
                for node in record["nodes"]:
                    if node["status"] == NODE_PENDING:
                        node["status"] = NODE_SKIPPED
            self._write(run_id, record)
            return record

    def list_all(self) -> list:
        records = []
        for child in self._ws.root.iterdir():
            if child.is_dir() and is_valid_run_id(child.name):
                record = self.read(child.name)
                if record:
                    records.append(record)
        return records

    def list_recent(self, limit=50) -> list:
        records = sorted(self.list_all(), key=lambda r: r.get("started_at") or "", reverse=True)
        return records[:limit]

    def mark_interrupted(self) -> list:
        """At startup, any run still marked RUNNING was cut off by a restart."""
        fixed = []
        with self._lock:
            for record in self.list_all():
                if record.get("status") == RUN_RUNNING:
                    node = record.get("current_node")
                    self.finish(record["run_id"], RUN_FAILED,
                                error={"node": node, "message": "The run was interrupted by a server restart."})
                    fixed.append(record["run_id"])
        return fixed
