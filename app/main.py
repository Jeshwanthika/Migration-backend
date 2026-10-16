from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.container import build_container
from app.core.settings import Settings

logger = logging.getLogger("platform")


def _cleanup_loop(container, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            active = container.service.active_run_id
            deleted = container.workspace.cleanup_expired(
                container.store, container.settings.retention_days, protected=(active,) if active else ())
            container.workspace.cleanup_tmp()
            if deleted:
                logger.info("cleanup removed %d expired run(s)", len(deleted))
        except Exception:
            logger.exception("cleanup failed")
        stop.wait(container.settings.cleanup_interval_seconds)


def create_app(settings: Settings | None = None, registry=None) -> FastAPI:
    settings = settings or Settings.from_env()
    container = build_container(settings, registry)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        interrupted = container.store.mark_interrupted()
        if interrupted:
            logger.warning("marked %d interrupted run(s) as failed", len(interrupted))
        stop = threading.Event()
        thread = threading.Thread(target=_cleanup_loop, args=(container, stop), daemon=True, name="cleanup")
        thread.start()
        yield
        stop.set()

    app = FastAPI(title="Legacy Migration Platform", version="0.1.0", lifespan=lifespan)
    app.state.container = container
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)

    @app.exception_handler(HTTPException)
    async def http_error(_request, exc: HTTPException):
        detail = exc.detail
        if not isinstance(detail, dict):
            detail = {"code": "error", "message": str(detail)}
        return JSONResponse(status_code=exc.status_code, content=detail)

    return app


def app_factory() -> FastAPI:
    """Entry point for uvicorn: uvicorn app.main:app_factory --factory"""
    return create_app()
