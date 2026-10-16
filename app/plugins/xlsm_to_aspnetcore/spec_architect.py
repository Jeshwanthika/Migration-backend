"""Spec Architect (Phase 3): turns the analysis into a technology-neutral migration spec (FR-SP1..SP5).

One LLM call per chunk of procedures, then platform code merges the pieces. One small extra call
asks which entity names mean the same thing. The model only returns a name mapping, and the platform
applies it, so no content can be lost in that step.
"""
from __future__ import annotations

from pathlib import Path

from app.core.errors import BlockerError
from app.core.files import read_json, write_json_atomic
from app.core.llm import LlmError, LlmGateway, LlmPermanentError, LlmSchemaError, LlmTransientError, create_provider
from app.core.models import SEV_INFO, SEV_WARNING, new_flag
from app.core.schema_validation import schema_errors, validate_artifact
from app.plugins.xlsm_to_aspnetcore.chunker import make_chunks
from app.plugins.xlsm_to_aspnetcore.procedures import split_module
from app.plugins.xlsm_to_aspnetcore.spec_merge import apply_entity_merges, finish_spec, merge_chunks
from app.plugins.xlsm_to_aspnetcore.spec_prompts import (
    RECONCILE_SYSTEM, SYSTEM_PROMPT, build_chunk_prompt, build_reconcile_prompt,
)
from app.plugins.xlsm_to_aspnetcore.spec_render import render_spec_markdown

MAX_CONSECUTIVE_UNREACHABLE = 3
NODE = "spec_architect"


def _units(vba: dict, analysis: dict, max_chars: int) -> list:
    """List of (module, declarations, [(analysis_record, Procedure), ...]) in source order."""
    by_location = {(p["module"], p["start_line"]): p for p in analysis["procedures"]}
    units = []
    for module in vba["modules"]:
        declarations, procedures = split_module(module["code"])
        for chunk in make_chunks(procedures, max_chars):
            records = [(by_location[(module["name"], p.start_line)], p) for p in chunk
                       if (module["name"], p.start_line) in by_location]
            if records:
                units.append((module, declarations, records))
    return units


def build_spec(vba: dict, analysis: dict, gateway: LlmGateway, settings, progress=lambda text: None) -> dict:
    flags: list = []
    units = _units(vba, analysis, settings.chunk_max_chars)
    source_file = analysis.get("source_file") or vba.get("source_file", "")

    if not units:
        flags.append(new_flag("SPEC_NOTHING_TO_SPECIFY", SEV_WARNING,
                              "The analysis has no procedures, so the spec is empty.",
                              suggested_action="Check that the workbook contains VBA procedures."))
        parts = merge_chunks([])
        return finish_spec(parts, analysis, source_file, {"tokens": 0, "calls": 0, "chunks": 0}, flags)

    project_refs = sorted({ref for p in analysis["procedures"] for ref in p["reads"] + p["writes"]})
    results: list = []
    unreachable_in_a_row = 0
    per_module = {}
    for module, *_rest in units:
        per_module[module["name"]] = per_module.get(module["name"], 0) + 1
    seen_in_module: dict = {}

    for index, (module, declarations, records) in enumerate(units, start=1):
        name = module["name"]
        seen_in_module[name] = seen_in_module.get(name, 0) + 1
        progress(f"Writing the spec, {name} (chunk {index} of {len(units)})")
        so_far = merge_chunks(results)
        prompt = build_chunk_prompt(module, declarations, records, so_far["entities"], so_far["rules"], project_refs,
                                    seen_in_module[name], per_module[name])
        try:
            data = gateway.call_json(NODE, SYSTEM_PROMPT, prompt, validate=lambda d: schema_errors("spec_chunk", d))
            unreachable_in_a_row = 0
        except LlmPermanentError as exc:
            raise BlockerError(str(exc)) from exc
        except (LlmTransientError, LlmSchemaError) as exc:
            if isinstance(exc, LlmTransientError):
                unreachable_in_a_row += 1
                if unreachable_in_a_row >= MAX_CONSECUTIVE_UNREACHABLE:
                    raise BlockerError(f"The model could not be reached for {MAX_CONSECUTIVE_UNREACHABLE} chunks in a row. "
                                       f"Last error: {exc}") from exc
            else:
                unreachable_in_a_row = 0
            ids = ", ".join(rec["id"] for rec, _p in records[:4]) + ("..." if len(records) > 4 else "")
            flags.append(new_flag("SPEC_CHUNK_FAILED", SEV_WARNING,
                                  f"The model could not write the spec for part of {name} ({ids}). Nothing was guessed for it. {exc}",
                                  source_ref=records[0][0]["id"],
                                  suggested_action="Run the migration again, or specify these procedures by hand."))
            continue
        results.append(data)

    if not results:
        reasons = "; ".join(sorted({f["reason"].rsplit(". ", 1)[-1][:300] for f in flags if f["code"] == "SPEC_CHUNK_FAILED"}))
        raise BlockerError("The model could not produce any part of the spec. "
                           f"Reason: {reasons or 'unknown'}. See logs/llm/spec_architect.jsonl.")

    parts = merge_chunks(results)

    if len(parts["entities"]) >= 2:
        progress("Checking entity names")
        try:
            reply = gateway.call_json(NODE, RECONCILE_SYSTEM, build_reconcile_prompt(parts["entities"]),
                                      validate=lambda d: schema_errors("spec_reconcile", d))
            applied = apply_entity_merges(parts, reply["merge"])
            if applied:
                flags.append(new_flag("SPEC_ENTITIES_MERGED", SEV_INFO, f"{applied} entity name(s) were merged because they meant the same record type."))
        except LlmError as exc:
            flags.append(new_flag("SPEC_RECONCILE_SKIPPED", SEV_INFO, f"Entity names were not cross-checked: {exc}"))

    usage = {"tokens": gateway.tokens_used, "calls": gateway.calls, "chunks": len(units)}
    return finish_spec(parts, analysis, source_file, usage, flags)


def spec_architect_stage(state, ctx) -> dict:
    run_id = state["run_id"]
    ws = ctx.workspace
    vba_path, analysis_path = ws.artifact_path(run_id, "vba_modules"), ws.artifact_path(run_id, "analysis_model")
    if not vba_path.is_file() or not analysis_path.is_file():
        raise BlockerError("The analysis is missing, so there is nothing to write a spec from.")
    vba, analysis = read_json(vba_path), read_json(analysis_path)
    provider = ctx.llm_provider or create_provider(ctx.settings)
    record = ctx.run_store.read(run_id) or {}
    gateway = LlmGateway(provider, ctx.settings, log_dir=ws.logs_dir(run_id) / "llm",
                         tokens_before=record.get("tokens_used", 0))

    def progress(text: str) -> None:
        ctx.run_store.update(run_id, detail=text)

    try:
        spec = build_spec(vba, analysis, gateway, ctx.settings, progress)
    finally:
        ctx.run_store.update(run_id, detail=None)
    validate_artifact("migration_spec", spec)
    json_path = ws.artifact_path(run_id, "migration_spec")
    write_json_atomic(json_path, spec)
    md_path = ws.artifacts_dir(run_id) / "migration_spec.md"
    md_path.write_text(render_spec_markdown(spec), encoding="utf-8")
    return {"spec_path": str(json_path), "spec_markdown_path": str(md_path), "flags": spec["flags"],
            "tokens_used": gateway.tokens_used}
