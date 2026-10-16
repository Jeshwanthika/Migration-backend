"""Extractor: reads VBA code with olevba. No LLM. Macros are never executed (D-4)."""
from __future__ import annotations

from pathlib import Path

from app.core.errors import BlockerError
from app.core.files import write_json_atomic
from app.core.models import SEV_INFO, SEV_WARNING, new_flag
from app.core.schema_validation import validate_artifact
from app.plugins.xlsm_to_aspnetcore.module_types import (
    classify_module, meaningful_line_count, module_name,
)

SCHEMA_VERSION = "1.0"
KEPT_FINDING_TYPES = ("AutoExec", "Suspicious", "IOC")
MAX_FINDINGS = 200


def read_macros(path: Path):
    """Return (macros, findings) from olevba.

    macros:   list of (stream_path, vba_filename, code)
    findings: list of (type, keyword, description)
    Any olevba failure becomes a BlockerError with a plain message.
    """
    try:
        from oletools.olevba import VBA_Parser
    except ImportError as exc:
        raise BlockerError("The 'oletools' package is not installed on the server (pip install oletools).") from exc
    try:
        parser = VBA_Parser(str(path))
    except Exception as exc:
        raise BlockerError(f"The VBA project could not be opened: {exc}") from exc
    try:
        if not parser.detect_vba_macros():
            return [], []
        macros = [(stream, vba_filename, code) for (_f, stream, vba_filename, code) in parser.extract_macros()]
        try:
            findings = [(t, k, d) for (t, k, d) in (parser.analyze_macros(show_decoded_strings=False) or [])]
        except Exception:
            findings = []  # findings are informational only
        return macros, findings
    except Exception as exc:
        raise BlockerError(f"The VBA project could not be read: {exc}") from exc
    finally:
        try:
            parser.close()
        except Exception:
            pass


def _clean_code(code) -> str:
    if isinstance(code, bytes):
        code = code.decode("utf-8", errors="replace")
    return (code or "").replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def build_artifact(source_file: str, macros, findings, max_vba_lines: int) -> dict:
    """Turn raw olevba output into the vba_modules artifact. Pure function, easy to test."""
    flags = []
    modules = []
    used_names = {}
    skipped_empty = 0
    total_lines = 0

    for stream, vba_filename, raw_code in macros:
        code = _clean_code(raw_code)
        if meaningful_line_count(code) == 0:
            skipped_empty += 1
            continue
        fallback = Path(vba_filename or stream or "Module").stem or "Module"
        name = module_name(code, fallback)
        used_names[name] = used_names.get(name, 0) + 1
        if used_names[name] > 1:
            flags.append(new_flag("DUPLICATE_MODULE_NAME", SEV_WARNING,
                                  f"Two modules are named {name}. The second was renamed.",
                                  source_ref=name))
            name = f"{name}_{used_names[name]}"
        line_count = len(code.splitlines())
        total_lines += line_count
        modules.append({
            "name": name,
            "type": classify_module(name, code, vba_filename or ""),
            "stream": stream or "",
            "line_count": line_count,
            "code": code,
        })

    if total_lines > max_vba_lines:
        raise BlockerError(
            f"The VBA project has {total_lines:,} lines, which is over the limit of {max_vba_lines:,}. "
            "Raise MAX_VBA_LINES in the settings or split the workbook."
        )
    if not modules:
        flags.append(new_flag(
            "NO_CODE_MODULES", SEV_WARNING,
            "The workbook has a VBA project but it contains no code, only empty modules.",
            suggested_action="Check that this is the right workbook.",
        ))
    elif skipped_empty:
        flags.append(new_flag("EMPTY_MODULES_SKIPPED", SEV_INFO,
                              f"{skipped_empty} module(s) with no code were left out."))

    kept = []
    for type_, keyword, description in findings:
        if type_ in KEPT_FINDING_TYPES and len(kept) < MAX_FINDINGS:
            kept.append({"type": str(type_), "keyword": str(keyword), "description": str(description)})

    return {
        "schema_version": SCHEMA_VERSION,
        "source_file": source_file,
        "modules": modules,
        "findings": kept,
        "flags": flags,
    }


def extractor_stage(state, ctx) -> dict:
    run_id = state["run_id"]
    ws = ctx.workspace
    input_files = sorted(Path(ws.input_dir(run_id)).glob("input.*"))
    if not input_files:
        raise BlockerError("The uploaded file is missing from the run folder.")
    macros, findings = read_macros(input_files[0])
    record = ctx.run_store.read(run_id) or {}
    artifact = build_artifact(record.get("filename", input_files[0].name), macros, findings,
                              ctx.settings.max_vba_lines)
    validate_artifact("vba_modules", artifact)
    out_path = ws.artifact_path(run_id, "vba_modules")
    write_json_atomic(out_path, artifact)
    return {"vba_modules_path": str(out_path), "flags": artifact["flags"]}
