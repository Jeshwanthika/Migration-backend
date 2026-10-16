from __future__ import annotations

import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from app.core.run_service import safe_filename
from app.core.workspace import ARTIFACT_FILES, is_valid_run_id
from app.core.files import read_json, safe_child

router = APIRouter(prefix="/api")


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _container(request: Request):
    return request.app.state.container


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/skills")
def list_skills(request: Request):
    return _container(request).registry.list_manifests()


@router.post("/runs", status_code=202)
def create_run(request: Request, skill_id: str = Form(...), file: UploadFile = File(...)):
    c = _container(request)
    plugin = c.registry.find(skill_id)
    if plugin is None:
        raise _error(400, "unknown_skill", f"Unknown migration skill: {skill_id}")
    if not c.service.try_acquire():
        raise _error(409, "run_active", "A migration is already running. Wait for it to finish, then upload again.")

    tmp_path = None
    started = False
    try:
        tmp_path = c.workspace.tmp_dir() / f"{uuid.uuid4().hex}.upload"
        written = 0
        limit = c.settings.max_upload_bytes
        with open(tmp_path, "wb") as out:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    raise _error(413, "file_too_large", f"The file is larger than the {c.settings.max_upload_mb} MB limit.")
                out.write(chunk)

        filename = safe_filename(file.filename or "")
        result = plugin.validate_input(tmp_path, filename, limit)
        if not result.ok:
            raise _error(result.http_status, result.code, result.message)

        record = c.service.create_run(plugin, tmp_path, filename)
        tmp_path = None  # moved into the run folder
        threading.Thread(target=c.runner.run, args=(record["run_id"],), daemon=True,
                         name=f"run-{record['run_id'][:8]}").start()
        started = True
        return {"run_id": record["run_id"]}
    finally:
        if tmp_path is not None:
            Path(tmp_path).unlink(missing_ok=True)
        if not started:
            c.service.release()


@router.get("/runs")
def list_runs(request: Request):
    return _container(request).store.list_recent()


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request):
    record = _container(request).store.read(run_id)
    if record is None:
        raise _error(404, "run_not_found", "No run with that id.")
    return record


@router.get("/runs/{run_id}/artifacts/{name}")
def get_artifact(run_id: str, name: str, request: Request):
    c = _container(request)
    if not is_valid_run_id(run_id) or c.store.read(run_id) is None:
        raise _error(404, "run_not_found", "No run with that id.")
    if name not in ARTIFACT_FILES:
        raise _error(404, "artifact_unknown", f"Unknown artifact: {name}")
    path = c.workspace.artifact_path(run_id, name)
    if not path.is_file():
        raise _error(404, "artifact_not_ready", "This artifact has not been produced yet.")
    return read_json(path)


@router.get("/runs/{run_id}/spec.md", response_class=PlainTextResponse)
def get_spec_markdown(run_id: str, request: Request):
    c = _container(request)
    if not is_valid_run_id(run_id) or c.store.read(run_id) is None:
        raise _error(404, "run_not_found", "No run with that id.")
    path = c.workspace.artifacts_dir(run_id) / "migration_spec.md"
    if not path.is_file():
        raise _error(404, "artifact_not_ready", "The spec has not been produced yet.")
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8")


MAX_VIEW_BYTES = 512 * 1024


@router.get("/runs/{run_id}/app-file", response_class=PlainTextResponse)
def get_app_file(run_id: str, path: str, request: Request):
    """Read one generated source file so the UI can show it. Only text inside output/app/ is served."""
    c = _container(request)
    if not is_valid_run_id(run_id) or c.store.read(run_id) is None:
        raise _error(404, "run_not_found", "No run with that id.")
    target = safe_child(c.workspace.output_dir(run_id) / "app", path)
    if target is None:
        raise _error(404, "file_not_found", "No such file in the generated app.")
    if target.stat().st_size > MAX_VIEW_BYTES:
        raise _error(413, "file_too_large", "This file is too large to show here.")
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise _error(415, "not_text", "This file is not text.")
    return PlainTextResponse(text, media_type="text/plain; charset=utf-8")


def _package_path(c, run_id: str):
    if not is_valid_run_id(run_id) or c.store.read(run_id) is None:
        raise _error(404, "run_not_found", "No run with that id.")
    found = sorted(c.workspace.output_dir(run_id).glob("*_migration.zip"))
    if not found:
        raise _error(404, "artifact_not_ready", "The zip has not been produced yet.")
    return found[0]


@router.get("/runs/{run_id}/package")
def get_package_info(run_id: str, request: Request):
    path = _package_path(_container(request), run_id)
    return {"file_name": path.name, "size_bytes": path.stat().st_size}


@router.get("/runs/{run_id}/download")
def download_package(run_id: str, request: Request):
    path = _package_path(_container(request), run_id)
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.get("/runs/{run_id}/report.md", response_class=PlainTextResponse)
def get_report(run_id: str, request: Request):
    c = _container(request)
    if not is_valid_run_id(run_id) or c.store.read(run_id) is None:
        raise _error(404, "run_not_found", "No run with that id.")
    path = c.workspace.artifacts_dir(run_id) / "MIGRATION_REPORT.md"
    if not path.is_file():
        raise _error(404, "artifact_not_ready", "The report has not been produced yet.")
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8")
