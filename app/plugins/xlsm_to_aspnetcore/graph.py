"""The LangGraph graph for this skill. Phase 6 adds packager."""
from __future__ import annotations

import operator
from pathlib import Path
from typing import Annotated, Optional, TypedDict

from app.core.errors import BlockerError
from app.core.stage_runner import route_after_stage, run_stage
from app.plugins.xlsm_to_aspnetcore.analyzer import analyzer_stage
from app.plugins.xlsm_to_aspnetcore.extractor import extractor_stage
from app.plugins.xlsm_to_aspnetcore.generator import generator_stage
from app.plugins.xlsm_to_aspnetcore.intake import check_xlsm
from app.plugins.xlsm_to_aspnetcore.packager import packager_stage
from app.plugins.xlsm_to_aspnetcore.spec_architect import spec_architect_stage
from app.plugins.xlsm_to_aspnetcore.validator import validator_stage


class MigrationState(TypedDict, total=False):
    run_id: str
    skill_id: str
    workspace_path: str
    input_path: str
    vba_modules_path: str
    analysis_path: str
    spec_path: str
    spec_markdown_path: str
    manifest_path: str
    validation_path: str
    zip_path: str
    flags: Annotated[list, operator.add]
    tokens_used: int
    error: Optional[dict]


def intake_check_stage(state, ctx) -> dict:
    """Re-checks the stored upload so the progress panel shows the step.
    The same check already rejected bad files before the run was created."""
    run_id = state["run_id"]
    inputs = sorted(Path(ctx.workspace.input_dir(run_id)).glob("input.*"))
    if not inputs:
        raise BlockerError("The uploaded file is missing from the run folder.")
    record = ctx.run_store.read(run_id) or {}
    result = check_xlsm(inputs[0], record.get("filename", "upload.xlsm"), ctx.settings.max_upload_bytes)
    if not result.ok:
        raise BlockerError(result.message)
    return {"input_path": str(inputs[0])}


# Each later phase adds one entry here. Order matters.
STAGE_FUNCTIONS = {
    "intake_check": intake_check_stage,
    "extractor": extractor_stage,
    "analyzer": analyzer_stage,
    "spec_architect": spec_architect_stage,
    "generator": generator_stage,
    "validator": validator_stage,
    "packager": packager_stage,
}


def enabled_stage_names(settings) -> list:
    unknown = [n for n in settings.enabled_stages if n not in STAGE_FUNCTIONS]
    if unknown:
        raise ValueError(
            f"ENABLED_STAGES lists {', '.join(unknown)}, which this build does not include yet. "
            f"Available: {', '.join(STAGE_FUNCTIONS)}."
        )
    return [n for n in STAGE_FUNCTIONS if n in settings.enabled_stages]


def build_graph(ctx):
    from langgraph.graph import END, START, StateGraph

    names = enabled_stage_names(ctx.settings)
    graph = StateGraph(MigrationState)
    for name in names:
        fn = STAGE_FUNCTIONS[name]
        graph.add_node(name, lambda state, _fn=fn, _name=name: run_stage(_name, _fn, state, ctx))
    graph.add_edge(START, names[0])
    for index, name in enumerate(names):
        target = names[index + 1] if index + 1 < len(names) else END
        graph.add_conditional_edges(name, route_after_stage, {"continue": target, "stop": END})
    return graph.compile()
