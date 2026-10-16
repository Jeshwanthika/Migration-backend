"""Runs the plugin's graph for one run, in a background thread."""
from __future__ import annotations

from app.core.context import PluginContext
from app.core.models import RUN_COMPLETED, RUN_COMPLETED_WITH_WARNINGS, RUN_FAILED, has_warnings


class GraphRunner:
    def __init__(self, settings, store, workspace, registry, on_finished):
        self._settings = settings
        self._store = store
        self._workspace = workspace
        self._registry = registry
        self._on_finished = on_finished

    def run(self, run_id: str) -> None:
        log = None
        try:
            record = self._store.read(run_id)
            if record is None:
                return
            plugin = self._registry.get(record["skill_id"])
            ctx = PluginContext(self._settings, self._store, self._workspace)
            log = ctx.logger(run_id)
            graph = plugin.build_graph(ctx)
            final = graph.invoke(plugin.initial_state(record, ctx))
            self._finalize(run_id, final)
            log.info("run finished")
        except Exception as exc:  # a run never takes the platform down
            if log is not None:
                log.exception("run crashed")
            try:
                current = (self._store.read(run_id) or {}).get("current_node")
                self._store.finish(
                    run_id, RUN_FAILED,
                    error={"node": current, "message": f"The run failed unexpectedly: {exc.__class__.__name__}: {exc}"},
                )
            except Exception:
                pass
        finally:
            self._on_finished(run_id)

    def _finalize(self, run_id: str, final: dict) -> None:
        error = final.get("error")
        if error:
            self._store.finish(run_id, RUN_FAILED, error=error)
            return
        status = RUN_COMPLETED_WITH_WARNINGS if has_warnings(final.get("flags")) else RUN_COMPLETED
        self._store.finish(run_id, status)
