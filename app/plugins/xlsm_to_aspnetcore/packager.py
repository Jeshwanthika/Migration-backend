"""Packager (Phase 6): writes MIGRATION_REPORT.md and zips the app, the spec and the results with zipfile.

The zip is produced even when the build failed; the report says so. Nothing outside output/app and the run's
artifacts is ever added, and `.env` files, build folders and logs are left out."""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

from app.core.errors import BlockerError
from app.core.files import read_json
from app.core.models import SEV_BLOCKER, SEV_INFO, SEV_WARNING, new_flag, utc_now_iso

EXCLUDED_DIRS = {"bin", "obj", ".vs", ".git", "__pycache__", "node_modules"}
EXCLUDED_SUFFIXES = (".user", ".suo", ".pyc")
MAX_LISTED = 30

DOC_ARTIFACTS = [  # (artifact file name, name inside the zip)
    ("migration_spec.md", "docs/migration_spec.md"),
    ("migration_spec.json", "docs/migration_spec.json"),
    ("analysis_model.json", "docs/analysis_model.json"),
    ("generation_manifest.json", "docs/generation_manifest.json"),
    ("validation_results.json", "docs/validation_results.json"),
]


def is_excluded(relative: Path) -> bool:
    parts = relative.parts
    name = parts[-1].lower()
    if any(p.lower() in EXCLUDED_DIRS for p in parts[:-1]):
        return True
    return name == ".env" or name.startswith(".env.") or name.endswith(EXCLUDED_SUFFIXES)


def collect_app_files(app_dir: Path) -> list:
    """Relative paths of the files to ship, sorted. Symlinks and anything outside app_dir are skipped."""
    root = app_dir.resolve()
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d.lower() not in EXCLUDED_DIRS and not (Path(dirpath) / d).is_symlink())
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(root)
            if path.is_symlink() or is_excluded(rel):
                continue
            found.append(rel)
    return found


def _count(flags: list, severity: str) -> int:
    return sum(1 for f in flags if f.get("severity") == severity)


def build_report(*, source_file: str, spec: dict, manifest: dict, validation, flags: list, files_in_zip: int, tokens: int) -> str:
    app = manifest["app_name"]
    out = [f"# Migration report: {source_file}", "", f"Generated {utc_now_iso()} by the migration platform.", ""]

    result = validation["result"] if validation else None
    verdict = {"passed": "**The generated app builds.** It has not been tested beyond that.",
               "build_failed": "**The generated app does not compile yet.** Errors are listed below.",
               "restore_failed": "**NuGet packages could not be restored, so the app was not built.**",
               "timed_out": "**The build did not finish within the time limit.**",
               None: "**The app was not built** (the build check was not part of this run)."}[result]
    out += ["## Summary", "", verdict, "",
            f"- Generated app: `{app}` ({len(manifest['files'])} files, {len(manifest['stubs'])} stubs).",
            f"- Found in the VBA: {len(spec['entities'])} entities, {len(spec['rules'])} rules, {len(spec['screens'])} screens, "
            f"{len(spec['workflows'])} workflows, {len(spec['reports'])} reports.",
            f"- Flags: {_count(flags, SEV_BLOCKER)} blockers, {_count(flags, SEV_WARNING)} warnings, {_count(flags, SEV_INFO)} notes.",
            f"- Model tokens used: {tokens:,}.", ""]

    out += ["## How to run", "", "Requires the .NET 8 SDK.", "", "```", f"cd app/{app}", "dotnet run", "```", "",
            "Open the address printed in the console. The app starts with no records: only the VBA logic was migrated, not the workbook's data.", ""]

    out += ["## Build result", ""]
    if validation is None:
        out += ["Not built. Run `dotnet build` in the `app` folder to check it.", ""]
    else:
        out += [f"- .NET SDK {validation['dotnet_version']}",
                f"- Restore: {validation['restore']['status']}. Build: {validation['build']['status']}.",
                f"- {validation['warning_count']} compiler warning(s), {len(validation['errors'])} error(s).", ""]
        for e in validation["errors"][:MAX_LISTED]:
            where = f" in `{e['file']}:{e['line']}`" if e.get("file") else ""
            spec_ids = f" (spec {', '.join(e['spec_refs'])})" if e.get("spec_refs") else ""
            out.append(f"- `{e['code']}` {e['message']}{where}{spec_ids}")
        if len(validation["errors"]) > MAX_LISTED:
            out.append(f"- ... and {len(validation['errors']) - MAX_LISTED} more in `docs/validation_results.json`.")
        if validation["errors"]:
            out.append("")

    out += ["## Needs your attention", ""]
    todo = False
    for s in manifest["stubs"]:
        todo = True
        out.append(f"- `{s['spec_id']}` {s['method']} is a stub ({s['cause'].replace('_', ' ')}): {s['reason']}")
    for u in manifest["uncovered_spec_items"]:
        todo = True
        out.append(f"- `{u['id']}` was not generated: {u['reason']}")
    for item in spec["stubs"][:MAX_LISTED]:
        todo = True
        out.append(f"- VBA procedure `{item['module']}.{item['name']}` is {item['level']}: {item['reason']}")
    if not todo:
        out.append("Nothing was stubbed. Review the generated logic anyway before relying on it.")
    out += ["", "Search the code for `MIGRATION-TODO` to find every place that needs a decision.", ""]

    serious = [f for f in flags if f.get("severity") in (SEV_WARNING, SEV_BLOCKER) and f.get("code") not in ("BUILD_ERROR",)]
    out += ["## Warnings", ""]
    if not serious:
        out.append("None.")
    for f in serious[:MAX_LISTED]:
        ref = f" `{f['source_ref']}`" if f.get("source_ref") else ""
        out.append(f"- **{f['severity']}** {f['code']}{ref}: {f['reason']}")
    if len(serious) > MAX_LISTED:
        out.append(f"- ... and {len(serious) - MAX_LISTED} more.")
    out.append("")

    out += ["## What is in this zip", "",
            f"- `app/`: the ASP.NET Core 8 Razor Pages solution ({files_in_zip} files; `bin`, `obj` and `.env` files are never included).",
            "- `docs/`: the migration spec (Markdown and JSON), the code analysis, the generation manifest and the build results.",
            "- `MIGRATION_REPORT.md`: this file.", "",
            "## Limits of this migration", "",
            "- Only VBA code was read. Sheet contents, named ranges, table definitions and UserForm layouts were not available.",
            "- Generated logic comes from a language model. It is a starting point to review, not a verified port.",
            "- PDF and Excel report output, and anything marked unsupported, are stubs.", ""]
    return "\n".join(out)


def package(app_dir: Path, artifacts: dict, report: str, zip_path: Path) -> int:
    """Write the zip atomically. artifacts maps names inside the zip to source files. Returns the file count."""
    files = collect_app_files(app_dir)
    if not files:
        raise BlockerError("The generated app folder is empty, so there is nothing to package.")
    tmp = zip_path.with_suffix(".zip.part")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("MIGRATION_REPORT.md", report)
            for arc, src in artifacts.items():
                z.write(src, arc)
            for rel in files:
                z.write(app_dir.resolve() / rel, "app/" + rel.as_posix())
        os.replace(tmp, zip_path)
    finally:
        tmp.unlink(missing_ok=True)
    return len(files)


def packager_stage(state, ctx) -> dict:
    run_id = state["run_id"]
    ws = ctx.workspace
    manifest_path, spec_path = ws.artifact_path(run_id, "generation_manifest"), ws.artifact_path(run_id, "migration_spec")
    app_dir = ws.output_dir(run_id) / "app"
    if not manifest_path.is_file() or not spec_path.is_file() or not app_dir.is_dir():
        raise BlockerError("The generated app is missing, so there is nothing to package.")
    manifest, spec = read_json(manifest_path), read_json(spec_path)
    validation_path = ws.artifact_path(run_id, "validation_results")
    validation = read_json(validation_path) if validation_path.is_file() else None

    flags = list(state.get("flags") or [])
    if not flags:  # the stage was run on its own: gather what earlier stages recorded
        flags = list(spec.get("flags", [])) + list(manifest.get("flags", []))
    record = ctx.run_store.read(run_id) or {}

    artifacts = {}
    for name, arc in DOC_ARTIFACTS:
        src = ws.artifacts_dir(run_id) / name
        if src.is_file():
            artifacts[arc] = src

    zip_path = ws.output_dir(run_id) / f"{manifest['app_name']}_migration.zip"
    count = len(collect_app_files(app_dir))
    report = build_report(source_file=spec["source_file"], spec=spec, manifest=manifest, validation=validation,
                          flags=flags, files_in_zip=count, tokens=record.get("tokens_used", 0))
    (ws.artifacts_dir(run_id) / "MIGRATION_REPORT.md").write_text(report, encoding="utf-8", newline="\n")
    package(app_dir, artifacts, report, zip_path)
    size_kb = max(1, zip_path.stat().st_size // 1024)
    note = new_flag("PACKAGED", SEV_INFO, f"Packaged {count} files into {zip_path.name} ({size_kb} KB).")
    return {"zip_path": str(zip_path), "flags": [note]}
