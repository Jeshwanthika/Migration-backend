from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.logging_setup import get_run_logger
from app.core.run_store import RunStore
from app.core.settings import Settings
from app.core.workspace import Workspace


@dataclass
class PluginContext:
    """What every stage function receives (the AgentContext of the design)."""
    settings: Settings
    run_store: RunStore
    workspace: Workspace
    llm_provider: Any = None  # tests inject a fake; normally built from settings
    command_runner: Any = None  # tests inject a fake for `dotnet`; normally runs the real command

    def logger(self, run_id: str):
        return get_run_logger(self.workspace.logs_dir(run_id), run_id)
