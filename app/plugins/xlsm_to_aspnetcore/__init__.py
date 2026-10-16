from __future__ import annotations

from pathlib import Path

from app.plugins.base import PluginManifest, SkillPlugin
from app.plugins.xlsm_to_aspnetcore.graph import build_graph, enabled_stage_names
from app.plugins.xlsm_to_aspnetcore.intake import check_xlsm


class XlsmToAspNetCorePlugin(SkillPlugin):
    manifest = PluginManifest(
        id="xlsm-to-aspnetcore",
        name="Excel VBA to ASP.NET Core",
        version="0.1.0",
        source_stack="Excel VBA (.xlsm)",
        target_stack="ASP.NET Core 8 (Razor Pages)",
        extensions=(".xlsm",),
    )

    def stage_names(self, settings) -> list:
        return enabled_stage_names(settings)

    def validate_input(self, path: Path, filename: str, max_upload_bytes: int):
        return check_xlsm(path, filename, max_upload_bytes)

    def initial_state(self, record: dict, ctx) -> dict:
        run_id = record["run_id"]
        return {
            "run_id": run_id,
            "skill_id": record["skill_id"],
            "workspace_path": str(ctx.workspace.run_dir(run_id)),
            "flags": [],
            "tokens_used": 0,
            "error": None,
        }

    def build_graph(self, ctx):
        return build_graph(ctx)


PLUGIN = XlsmToAspNetCorePlugin
