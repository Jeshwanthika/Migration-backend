"""Validator: runs `dotnet restore` and `dotnet build` on the generated app and records the outcome.

A failed build is not a failed run: the result is written, a Warning flag is raised, and the Packager still
zips the app with the failure in its report (spec). Only a missing .NET SDK or a missing app ends the run."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from app.core.errors import BlockerError
from app.core.files import read_json, write_json_atomic
from app.core.models import SEV_INFO, SEV_WARNING, new_flag
from app.core.schema_validation import validate_artifact

MAX_ERRORS = 50
MAX_ERROR_FLAGS = 15
TAIL_CHARS = 4000

# C:\x\Foo.cs(12,5): error CS0103: The name 'x' does not exist [C:\x\App.csproj]
_WITH_FILE = re.compile(r"^(?P<file>.+?)\((?P<line>\d+)(?:,(?P<col>\d+))?(?:,\d+,\d+)?\):\s*(?P<sev>error|warning)\s+(?P<code>[A-Za-z]+\d+):\s*(?P<msg>.*?)(?:\s+\[[^\]]+\])?\s*$")
# error NU1101: Unable to find package X   |   MSBUILD : error MSB1009: Project file does not exist.
_NO_FILE = re.compile(r"^(?:.*?:\s*)?(?P<sev>error|warning)\s+(?P<code>[A-Za-z]+\d+):\s*(?P<msg>.*?)(?:\s+\[[^\]]+\])?\s*$")


def run_command(args: list, cwd: Path, timeout: int) -> tuple:
    """Run one command without a shell. Returns (exit_code, output, timed_out). Tests replace this function."""
    env = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1",
               MSBUILDDISABLENODEREUSE="1")
    try:
        done = subprocess.run(args, cwd=str(cwd), env=env, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or b"") + (exc.stderr or b"")
        return None, partial.decode("utf-8", errors="replace"), True
    out = (done.stdout or b"") + b"\n" + (done.stderr or b"")
    return done.returncode, out.decode("utf-8", errors="replace"), False


def parse_messages(output: str, app_dir: Path) -> tuple:
    """Return (errors, warning_count). Duplicates (MSBuild repeats them in its summary) are removed."""
    errors, seen, warnings = [], set(), set()
    for raw in output.splitlines():
        line = raw.strip()
        m = _WITH_FILE.match(line)
        if m:
            file, ln, col = _relative(m["file"], app_dir), int(m["line"]), int(m["col"] or 0)
        else:
            m = _NO_FILE.match(line)
            if not m:
                continue
            file, ln, col = None, None, None
        key = (file, ln, col, m["code"], m["msg"])
        if m["sev"] == "warning":
            warnings.add(key)
            continue
        if key in seen:
            continue
        seen.add(key)
        item = {"code": m["code"], "message": m["msg"][:500]}
        if file:
            item.update(file=file, line=ln, column=col)
        errors.append(item)
    return errors, len(warnings)


def _relative(file: str, app_dir: Path) -> str:
    try:
        return Path(file).resolve().relative_to(app_dir.resolve()).as_posix()
    except (ValueError, OSError):
        return file.replace("\\", "/")


def _step(code, output, seconds, timed_out, failed_ok=True) -> dict:
    status = "timed_out" if timed_out else ("ok" if code == 0 else "failed")
    return {"status": status, "exit_code": code, "seconds": round(seconds, 1), "output_tail": output[-TAIL_CHARS:]}


def validate_app(app_dir: Path, app_name: str, manifest: dict, timeout: int, runner=None) -> tuple:
    """Build the app. Returns (results, flags). Raises BlockerError only when there is nothing to build with."""
    runner = runner or run_command
    dotnet = shutil.which("dotnet")
    if dotnet is None and runner is run_command:
        raise BlockerError(".NET SDK not found. Install the .NET 8 SDK (https://dotnet.microsoft.com/download), "
                           "reopen the terminal so `dotnet` is on PATH, and run again.")
    dotnet = dotnet or "dotnet"
    solution = app_dir / f"{app_name}.sln"
    if not solution.is_file():
        raise BlockerError("The generated app has no solution file, so there is nothing to build.")

    code, out, _t = runner([dotnet, "--version"], app_dir, 60)
    version = out.strip().splitlines()[0] if code == 0 and out.strip() else "unknown"

    flags, errors, warnings = [], [], 0
    skipped = {"status": "skipped", "exit_code": None, "seconds": 0.0, "output_tail": ""}
    t0 = time.time()
    code, out, timed_out = runner([dotnet, "restore", solution.name, "--nologo"], app_dir, timeout)
    restore = _step(code, out, time.time() - t0, timed_out)
    build = skipped
    if restore["status"] == "ok":
        t0 = time.time()
        code, out, timed_out = runner([dotnet, "build", solution.name, "--no-restore", "--nologo", "-v", "q", "-clp:NoSummary"], app_dir, timeout)
        build = _step(code, out, time.time() - t0, timed_out)
        errors, warnings = parse_messages(out, app_dir)
        result = "passed" if build["status"] == "ok" else ("timed_out" if timed_out else "build_failed")
    else:
        errors, _w = parse_messages(out, app_dir)
        result = "timed_out" if timed_out else "restore_failed"

    refs = {f["path"]: f["spec_refs"] for f in manifest.get("files", [])}
    for e in errors:
        if e.get("file") in refs:
            e["spec_refs"] = refs[e["file"]]
    errors = errors[:MAX_ERRORS]

    if result == "passed":
        flags.append(new_flag("BUILD_PASSED", SEV_INFO, f"The generated app restored and built with {warnings} compiler warning(s)."))
    elif result == "restore_failed":
        flags.append(new_flag("RESTORE_FAILED", SEV_WARNING,
                              "dotnet restore failed, so the app was not built. This is usually a network or NuGet source problem. "
                              + (errors[0]["message"] if errors else restore["output_tail"][-200:].strip()),
                              suggested_action="Check the internet connection and run `dotnet restore` in the app folder."))
    elif result == "timed_out":
        flags.append(new_flag("BUILD_TIMED_OUT", SEV_WARNING, f"The .NET build did not finish within {timeout} seconds.",
                              suggested_action="Increase DOTNET_TIMEOUT_SEC in .env and run again."))
    else:
        flags.append(new_flag("BUILD_FAILED", SEV_WARNING, f"The generated app does not compile: {len(errors)} error(s). "
                              "The app is still packaged, with the errors listed in the report.",
                              suggested_action="Fix the listed files by hand, or run the migration again."))
        for e in errors[:MAX_ERROR_FLAGS]:
            where = f"{e['file']}({e['line']})" if e.get("file") else "build"
            flags.append(new_flag("BUILD_ERROR", SEV_WARNING, f"{e['code']}: {e['message']}", source_ref=where,
                                  suggested_action=("Spec items: " + ", ".join(e["spec_refs"])) if e.get("spec_refs") else None))
        if len(errors) > MAX_ERROR_FLAGS:
            flags.append(new_flag("BUILD_ERRORS_TRUNCATED", SEV_INFO, f"{len(errors) - MAX_ERROR_FLAGS} more error(s) are in validation_results.json."))

    results = {"schema_version": "1.0", "app_name": app_name, "dotnet_version": version, "result": result,
               "restore": restore, "build": build, "errors": errors, "warning_count": warnings}
    return results, flags


def validator_stage(state, ctx) -> dict:
    run_id = state["run_id"]
    ws = ctx.workspace
    manifest_path = ws.artifact_path(run_id, "generation_manifest")
    if not manifest_path.is_file():
        raise BlockerError("The generated app is missing, so there is nothing to validate.")
    manifest = read_json(manifest_path)
    app_dir = ws.output_dir(run_id) / "app"
    ctx.run_store.update(run_id, detail="Running dotnet restore and build (the first run can take a few minutes)")
    try:
        results, flags = validate_app(app_dir, manifest["app_name"], manifest, ctx.settings.dotnet_timeout_sec,
                                      runner=getattr(ctx, "command_runner", None))
    finally:
        ctx.run_store.update(run_id, detail=None)
    validate_artifact("validation_results", results)
    path = ws.artifact_path(run_id, "validation_results")
    write_json_atomic(path, results)
    return {"validation_path": str(path), "flags": flags}
