"""Generator (Phase 4): writes the ASP.NET Core 8 Razor Pages app into output/app/ (FR-GN1..GN7).

Split of work:
* The platform writes the scaffold, entity classes, repositories, every page and every method
  signature, so the pieces always fit together.
* Gemini writes only method bodies for rules, workflows and reports, in batches.
* Anything unsupported, and any body that fails the safety checks, becomes a stub that throws
  NotImplementedException and carries the original VBA in a comment.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from app.core.errors import BlockerError
from app.core.files import read_json, write_json_atomic
from app.core.llm import LlmGateway, LlmPermanentError, LlmSchemaError, LlmTransientError, create_provider
from app.core.models import SEV_INFO, SEV_WARNING, new_flag
from app.core.schema_validation import schema_errors, validate_artifact
from app.plugins.xlsm_to_aspnetcore.gen.methods import (
    SYSTEM_PROMPT, build_batch_prompt, method_source, partial_file, validate_batch,
)
from app.plugins.xlsm_to_aspnetcore.gen.models import entity_files
from app.plugins.xlsm_to_aspnetcore.gen.pages import (
    entity_page_files, index_files, nav_links, reports_files, screen_files, workflows_files,
)
from app.plugins.xlsm_to_aspnetcore.gen.plan import build_plan
from app.plugins.xlsm_to_aspnetcore.gen.scaffold import scaffold_files

NODE = "generator"
MAX_CONSECUTIVE_UNREACHABLE = 3
MAX_METHODS_PER_BATCH = 8
MAX_STUB_VBA_LINES = 120


class FileSet:
    """Collects the files to write, with the metadata the manifest needs."""

    def __init__(self):
        self.items: dict = {}

    def add(self, path: str, content: str, kind: str, refs=(), stub: bool = False) -> None:
        self.items[path] = {"content": content, "kind": kind, "spec_refs": list(refs), "is_stub": stub}

    def add_many(self, files: dict, kind_of, refs_of=lambda p: ()) -> None:
        for path, content in files.items():
            self.add(path, content, kind_of(path), refs_of(path))


def _kind(path: str) -> str:
    if path.endswith(".sln") or path.endswith(".csproj") or path.endswith("Program.cs") or path.endswith(".gitignore"):
        return "scaffold"
    if "/Data/" in path:
        return "data"
    if "/Infrastructure/" in path:
        return "repository"
    if "/Models/" in path:
        return "model"
    if "/Services/" in path:
        return "service"
    if "/Pages/" in path or "/wwwroot/" in path:
        return "page"
    if path.endswith(".json"):
        return "config"
    return "scaffold"


def _procedure_sources(vba: dict, analysis: dict) -> dict:
    code_by_module = {m["name"]: m["code"].split("\n") for m in vba["modules"]}
    out = {}
    for rec in analysis["procedures"]:
        lines = code_by_module.get(rec["module"], [])
        out[rec["id"]] = (rec, "\n".join(lines[rec["start_line"] - 1:rec["end_line"]]))
    return out


def _stub_vba(m, sources: dict, spec_stubs: list) -> list:
    """[(title, lines)] of original VBA to quote in a stub, limited in length."""
    unsupported = {s["procedure_id"] for s in spec_stubs if s["level"] == "unsupported"}
    ids = [pid for pid in m.sources if pid in sources]
    chosen = [pid for pid in ids if pid in unsupported] or ids
    out, used = [], 0
    for pid in chosen:
        rec, code = sources[pid]
        lines = code.split("\n")
        room = MAX_STUB_VBA_LINES - used
        if room <= 0:
            break
        shown = lines[:room]
        if len(shown) < len(lines):
            shown.append("... (truncated)")
        out.append((f"{pid}, lines {rec['start_line']}-{rec['end_line']}", shown))
        used += len(shown)
    return out


def _batches(methods: list, sources: dict, max_chars: int) -> list:
    batches, current, size = [], [], 0
    for m in methods:
        weight = sum(len(sources[p][1]) for p in m.sources if p in sources) + len(m.spec.get("description", ""))
        if current and (size + weight > max_chars or len(current) >= MAX_METHODS_PER_BATCH):
            batches.append(current)
            current, size = [], 0
        current.append(m)
        size += weight
    if current:
        batches.append(current)
    return batches


def readme(plan, spec: dict, stubs: list, uncovered: list) -> str:
    lines = [f"# {plan.title}", "",
             f"Migrated from `{spec['source_file']}` by the migration platform. Only the VBA logic was migrated.",
             "No workbook data was carried over: records start empty and are kept in `Data/*.json`.", "",
             "## Run", "", "Requires the .NET 8 SDK.", "", "```", f"cd {plan.app}", "dotnet run", "```", "",
             "Open the address printed in the console. To build only: `dotnet build` in this folder.", "",
             "## What is in here", "",
             f"- `{plan.app}/Models`: one class per record type ({len(plan.entities)}).",
             f"- `{plan.app}/Infrastructure`: JSON file repository and small helpers.",
             f"- `{plan.app}/Services/BusinessRules.*.cs`: rules ({len(plan.rules)}), workflows ({len(plan.workflows)}) and reports ({len(plan.reports)}).",
             f"- `{plan.app}/Pages`: Razor Pages for home, records ({len(plan.entities)}), screens ({len(plan.screens)}), workflows and reports.", ""]
    lines += ["## Still to do", ""]
    if not stubs and not uncovered:
        lines += ["No stubs. Every item was migrated, but review the generated logic before relying on it.", ""]
    for s in stubs:
        lines.append(f"- `{s['spec_id']}` {s['method']} ({s['cause'].replace('_', ' ')}): {s['reason']}")
    for u in uncovered:
        lines.append(f"- `{u['id']}`: {u['reason']}")
    lines += ["", "Search the code for `MIGRATION-TODO` to find every place that needs attention.", ""]
    return "\n".join(lines)


def generate_app(spec: dict, vba: dict, analysis: dict, gateway: LlmGateway, settings, progress=lambda text: None):
    """Return (FileSet, manifest dict). Raises BlockerError when the run cannot continue."""
    flags: list = []
    plan = build_plan(spec)
    app = plan.app
    fs = FileSet()
    sources = _procedure_sources(vba, analysis)

    # ----- deterministic part -----
    fs.add_many(scaffold_files(app, plan.title, nav_links(plan)), _kind)
    entity_ref = {}
    for e in plan.entities:
        entity_ref[f"{app}/Models/{e.cls}.cs"] = [e.spec["id"]]
        entity_ref[f"{app}/Data/{e.cls}.json"] = [e.spec["id"]]
    fs.add_many(entity_files(app, plan), _kind, lambda p: entity_ref.get(p, ()))
    ent_pages = entity_page_files(app, plan)
    fs.add_many(ent_pages, lambda p: "page", lambda p: [e.spec["id"] for e in plan.entities if f"/Entities/{e.cls}." in p])
    scr_pages = screen_files(app, plan)
    fs.add_many(scr_pages, lambda p: "page", lambda p: [s.spec["id"] for s in plan.screens if p.startswith(f"{app}/Pages/{s.cls}.")])
    fs.add_many(workflows_files(app, plan), lambda p: "page", lambda p: [w.id for w in plan.workflows])
    fs.add_many(reports_files(app, plan), lambda p: "page", lambda p: [r.id for r in plan.reports])
    fs.add_many(index_files(app, plan, spec), lambda p: "page")

    # ----- method bodies -----
    bodies: dict = {}          # method id -> body text
    stub_info: dict = {}       # method id -> (cause, reason)
    for m in plan.methods:
        if m.stub_reason:
            stub_info[m.id] = ("unsupported", m.stub_reason)
            flags.append(new_flag("STUB_GENERATED", SEV_INFO, f"{m.spec['name']} was written as a stub: {m.stub_reason}", source_ref=m.id,
                                  suggested_action="Implement it by hand. The original VBA is quoted in the code."))

    llm_methods = [m for m in plan.methods if not m.stub_reason]
    batches = _batches(llm_methods, sources, settings.chunk_max_chars)
    produced_any = False
    unreachable_in_a_row = 0
    for index, batch in enumerate(batches, start=1):
        progress(f"Generating code, batch {index} of {len(batches)}")
        prompt = build_batch_prompt(plan, batch, sources)
        good: dict = {}

        def validate(data, _batch=batch, _good=good):
            errors = schema_errors("generated_methods", data)
            if errors:
                return errors
            errs, ok = validate_batch(_batch, data)
            _good.update(ok)
            return errs

        failure = None
        try:
            gateway.call_json(NODE, SYSTEM_PROMPT, prompt, validate=validate)
            unreachable_in_a_row = 0
        except LlmPermanentError as exc:
            raise BlockerError(str(exc)) from exc
        except (LlmTransientError, LlmSchemaError) as exc:
            failure = exc
            if isinstance(exc, LlmTransientError):
                unreachable_in_a_row += 1
                if unreachable_in_a_row >= MAX_CONSECUTIVE_UNREACHABLE:
                    raise BlockerError(f"The model could not be reached for {MAX_CONSECUTIVE_UNREACHABLE} batches in a row. "
                                       f"Last error: {exc}") from exc
            else:
                unreachable_in_a_row = 0
        if good:
            produced_any = True
        for m in batch:
            if m.id in good:
                bodies[m.id] = good[m.id]
            else:
                reason = f"The model's code for this was rejected or missing. {failure}" if failure else "The model's code for this was missing."
                stub_info[m.id] = ("generation_failed", reason)
                flags.append(new_flag("GENERATION_FAILED", SEV_WARNING, f"{m.spec['name']} ({m.id}) was written as a stub. {reason}",
                                      source_ref=m.id, suggested_action="Run the migration again, or implement it by hand."))
    if batches and not produced_any:
        raise BlockerError("The model produced no usable code. See logs/llm/generator.jsonl.")

    # ----- assemble partial class files -----
    groups = (("Rules", plan.rules), ("Workflows", plan.workflows), ("Reports", plan.reports))
    for name, methods in groups:
        if not methods:
            continue
        texts, stubbed = [], False
        for m in methods:
            if m.id in stub_info:
                stubbed = True
                texts.append(method_source(m, None, _stub_vba(m, sources, spec["stubs"]), stub_info[m.id][1]))
            else:
                texts.append(method_source(m, bodies[m.id]))
        fs.add(f"{app}/Services/BusinessRules.{name}.cs", partial_file(app, texts), "service", [m.id for m in methods], stubbed)

    # ----- manifest and README -----
    stubs = [{"spec_id": m.id, "method": m.name, "cause": stub_info[m.id][0], "reason": stub_info[m.id][1]}
             for m in plan.methods if m.id in stub_info]
    uncovered = [{"id": s["spec_id"], "reason": s["reason"]} for s in stubs if s["cause"] == "generation_failed"]
    fs.add("README.md", readme(plan, spec, stubs, uncovered), "docs")
    usage = {"tokens": gateway.tokens_used, "calls": gateway.calls, "batches": len(batches)}
    manifest = {
        "schema_version": "1.0", "app_name": app,
        "files": [{"path": p, "kind": i["kind"], "spec_refs": i["spec_refs"], "is_stub": i["is_stub"]} for p, i in sorted(fs.items.items())],
        "stubs": stubs, "uncovered_spec_items": uncovered, "flags": flags, "usage": usage,
    }
    return fs, manifest


def write_app(root: Path, fs: FileSet) -> None:
    """Write files only inside root (FR-GN4). Any path that escapes it is refused."""
    root = Path(root).resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for rel, item in fs.items.items():
        target = (root / rel).resolve()
        if root != target and root not in target.parents:
            raise BlockerError(f"Internal error: refused to write outside the app folder: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item["content"], encoding="utf-8", newline="\n")


def generator_stage(state, ctx) -> dict:
    run_id = state["run_id"]
    ws = ctx.workspace
    paths = [ws.artifact_path(run_id, n) for n in ("vba_modules", "analysis_model", "migration_spec")]
    if not all(p.is_file() for p in paths):
        raise BlockerError("The spec is missing, so there is nothing to generate from.")
    vba, analysis, spec = (read_json(p) for p in paths)
    provider = ctx.llm_provider or create_provider(ctx.settings)
    record = ctx.run_store.read(run_id) or {}
    gateway = LlmGateway(provider, ctx.settings, log_dir=ws.logs_dir(run_id) / "llm", tokens_before=record.get("tokens_used", 0))

    def progress(text: str) -> None:
        ctx.run_store.update(run_id, detail=text)

    try:
        fs, manifest = generate_app(spec, vba, analysis, gateway, ctx.settings, progress)
    finally:
        ctx.run_store.update(run_id, detail=None)
    validate_artifact("generation_manifest", manifest)
    write_app(ws.output_dir(run_id) / "app", fs)
    manifest_path = ws.artifact_path(run_id, "generation_manifest")
    write_json_atomic(manifest_path, manifest)
    return {"manifest_path": str(manifest_path), "flags": manifest["flags"], "tokens_used": gateway.tokens_used}
