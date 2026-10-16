from __future__ import annotations

import importlib
import pkgutil
from typing import Iterable, Optional

from app.plugins.base import SkillPlugin


class PluginRegistry:
    def __init__(self, plugins: Iterable[SkillPlugin]):
        self._plugins = {p.manifest.id: p for p in plugins}

    @classmethod
    def discover(cls) -> "PluginRegistry":
        """Import every sub-package of app.plugins and collect its PLUGIN class."""
        import app.plugins as package

        found = []
        for info in pkgutil.iter_modules(package.__path__):
            if not info.ispkg:
                continue
            module = importlib.import_module(f"app.plugins.{info.name}")
            plugin_cls = getattr(module, "PLUGIN", None)
            if plugin_cls is not None:
                found.append(plugin_cls())
        return cls(found)

    def find(self, skill_id: str) -> Optional[SkillPlugin]:
        return self._plugins.get(skill_id)

    def get(self, skill_id: str) -> SkillPlugin:
        plugin = self._plugins.get(skill_id)
        if plugin is None:
            raise KeyError(f"Unknown skill: {skill_id}")
        return plugin

    def list_manifests(self) -> list:
        return [p.manifest.to_dict() for p in self._plugins.values()]
