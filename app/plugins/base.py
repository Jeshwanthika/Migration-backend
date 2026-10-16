"""The contract every migration skill implements."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    version: str
    source_stack: str
    target_stack: str
    extensions: tuple

    def to_dict(self) -> dict:
        data = asdict(self)
        data["extensions"] = list(self.extensions)
        return data


@dataclass(frozen=True)
class IntakeResult:
    ok: bool
    http_status: int = 200
    code: str = "ok"
    message: str = ""


class SkillPlugin(ABC):
    manifest: PluginManifest

    @abstractmethod
    def stage_names(self, settings) -> list:
        """Names of the graph nodes that are switched on, in order."""

    @abstractmethod
    def validate_input(self, path: Path, filename: str, max_upload_bytes: int) -> IntakeResult:
        """Quick check of the uploaded file. A rejected file creates no run."""

    @abstractmethod
    def initial_state(self, record: dict, ctx) -> dict:
        """The starting state for the graph."""

    @abstractmethod
    def build_graph(self, ctx):
        """Return a compiled graph with an invoke(state) method."""
