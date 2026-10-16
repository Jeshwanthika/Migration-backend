"""Wraps every graph node so progress, errors and flags are recorded the same way."""
from __future__ import annotations

from app.core.errors import BlockerError
from app.core.models import NODE_DONE, NODE_FAILED


def run_stage(name, fn, state, ctx) -> dict:
    """Run one stage function and return the state update for the graph.

    fn(state, ctx) returns a dict of state updates. A BlockerError, or any other
    exception, ends the run: the update carries an `error` that the router checks.
    """
    run_id = state["run_id"]
    log = ctx.logger(run_id)
    ctx.run_store.set_node(run_id, name, "running")
    log.info(f"node started: {name}")
    try:
        update = fn(state, ctx) or {}
    except BlockerError as exc:
        message = str(exc)
        log.error(f"node failed: {name}: {message}")
        return _fail(ctx, run_id, name, message)
    except Exception as exc:  # unexpected: log the trace, show a short message
        log.exception(f"node crashed: {name}")
        return _fail(ctx, run_id, name, f"Unexpected error in {name}: {exc.__class__.__name__}: {exc}")
    flags = update.get("flags", [])
    ctx.run_store.set_node(run_id, name, NODE_DONE)
    ctx.run_store.add_progress(run_id, flags=len(flags), tokens=update.get("tokens_used", 0))
    log.info(f"node finished: {name}")
    update = dict(update)
    update.setdefault("flags", [])
    return update


def _fail(ctx, run_id, name, message) -> dict:
    ctx.run_store.set_node(run_id, name, NODE_FAILED)
    error = {"node": name, "message": message}
    ctx.run_store.update(run_id, error=error)
    return {"error": error, "flags": []}


def route_after_stage(state) -> str:
    """Conditional edge used after every node: stop on a blocker, otherwise continue."""
    return "stop" if state.get("error") else "continue"
