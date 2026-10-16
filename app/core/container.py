from __future__ import annotations

from dataclasses import dataclass

from app.core.graph_runner import GraphRunner
from app.core.plugin_registry import PluginRegistry
from app.core.run_service import RunService
from app.core.run_store import RunStore
from app.core.settings import Settings
from app.core.workspace import Workspace


@dataclass
class Container:
    settings: Settings
    workspace: Workspace
    store: RunStore
    registry: PluginRegistry
    service: RunService
    runner: GraphRunner


def build_container(settings: Settings, registry: PluginRegistry | None = None) -> Container:
    workspace = Workspace(settings.workspace_root)
    store = RunStore(workspace)
    registry = registry or PluginRegistry.discover()
    service = RunService(settings, store, workspace)
    runner = GraphRunner(settings, store, workspace, registry, service.release)
    return Container(settings, workspace, store, registry, service, runner)
