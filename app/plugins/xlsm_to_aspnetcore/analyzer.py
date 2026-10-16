"""Analyzer (Phase 2): finds every procedure and asks the LLM what each one does (FR-AN1..AN8).

The platform splits the code and records line numbers. The LLM adds role, summary, calls,
reads, writes and a support level. A rule scan adds the coverage-matrix flags the model may miss.
"""
from __future__ import annotations

import re

from app.core.errors import BlockerError
from app.core.files import read_json, write_json_atomic
from app.core.llm import LlmGateway, LlmPermanentError, LlmSchemaError, LlmTransientError, create_provider
from app.core.models import SEV_INFO, SEV_WARNING, new_flag
from app.core.schema_validation import schema_errors, validate_artifact
from app.plugins.xlsm_to_aspnetcore.analyzer_prompts import SYSTEM_PROMPT, build_prompt
from app.plugins.xlsm_to_aspnetcore.chunker import make_chunks
from app.plugins.xlsm_to_aspnetcore.procedures import procedure_id, signature, split_module
from app.plugins.xlsm_to_aspnetcore.scanner import IGNORABLE, scan_declarations, scan_procedure

SCHEMA_VERSION = "1.0"
SUPPORT_RANK = {"supported": 0, "partial": 1, "unsupported": 2}
MAX_CONSECUTIVE_UNREACHABLE = 3


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _default_record(module_name: str, proc, proc_id: str) -> dict:
    return {
        "id": proc_id, "module": module_name, "name": proc.name, "kind": proc.kind, "scope": proc.scope or "Public",
        "params": proc.params, "returns": proc.returns, "start_line": proc.start_line, "end_line": proc.end_line,
        "role": "utility", "summary": "", "calls": [], "reads": [], "writes": [],
        "support": "partial", "support_reason": "This procedure was not analyzed by the model.", "analyzed": False,
    }


def _strings(value) -> list:
    seen, out = set(), []
    for item in value or []:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _match_entries(chunk: list, entries: list) -> dict:
    """Map chunk procedure index -> LLM entry, by name and (when given) kind."""
    result, used = {}, set()
    for entry in entries:
        name = _norm(entry.get("name"))
        kind = _norm(entry.get("kind"))
        candidates = [i for i, p in enumerate(chunk) if _norm(p.name) == name and i not in used]
        if kind:
            exact = [i for i in candidates if _norm(chunk[i].kind) == kind]
            candidates = exact or candidates
        if candidates:
            result[candidates[0]] = entry
            used.add(candidates[0])
    return result


def _line_of(snippet: str, proc) -> int:
    """Find the physical line a snippet starts on. Handles statements joined from ' _' continuations."""
    wanted = _norm(snippet)
    if wanted:
        for offset, raw in enumerate(proc.lines):
            line = _norm(raw)
            if line.endswith(" _"):
                line = line[:-2].strip()
            if line and (wanted in line or wanted.startswith(line)):
                return proc.start_line + offset
    return proc.start_line


def _construct_flag(module: str, level: str, code: str, reason: str, line: int, snippet: str, action: str | None) -> dict:
    severity = SEV_INFO if level == IGNORABLE else SEV_WARNING
    return new_flag(code, severity, reason, support=None if level == IGNORABLE else level,
                    source_ref=f"{module}:{line}", snippet=(snippet or "")[:200] or None,
                    suggested_action=action or None)


def _group_scanned(scanned: list) -> list:
    """One entry per rule code in a procedure, with every line it was found on."""
    groups: dict = {}
    for item in scanned:
        groups.setdefault(item["code"], []).append(item)
    return list(groups.values())


def analyze_modules(vba: dict, gateway: LlmGateway, settings, progress=lambda text: None):
    """Return (analysis_model, flags). Raises BlockerError when the run cannot continue."""
    flags: list = []
    parsed = []
    for module in vba["modules"]:
        declarations, procedures = split_module(module["code"])
        parsed.append((module, declarations, procedures, make_chunks(procedures, settings.chunk_max_chars)))
    total_chunks = sum(len(chunks) for *_rest, chunks in parsed)

    taken_ids: set = set()
    all_signatures = {m["name"]: [] for m, *_ in parsed}
    for module, _decl, procedures, _chunks in parsed:
        all_signatures[module["name"]] = [p.name for p in procedures]

    modules_out, procedures_out = [], []
    done_chunks = 0
    unreachable_in_a_row = 0

    for module, declarations, procedures, chunks in parsed:
        name = module["name"]
        records = []
        for proc in procedures:
            records.append(_default_record(name, proc, procedure_id(name, proc, taken_ids)))
            if not proc.terminated:
                flags.append(new_flag("UNTERMINATED_PROCEDURE", SEV_WARNING,
                                      f"{proc.kind} {proc.name} has no matching End statement.",
                                      source_ref=f"{name}:{proc.start_line}"))
            if len(proc.text) > settings.chunk_max_chars:
                flags.append(new_flag("OVERSIZED_PROCEDURE", SEV_INFO,
                                      f"{proc.name} is larger than the chunk size, so it was sent to the model whole.",
                                      source_ref=f"{name}:{proc.start_line}"))
        index_of = {id(p): i for i, p in enumerate(procedures)}
        llm_constructs = [[] for _ in procedures]
        module_summary = ""

        for part, chunk in enumerate(chunks, start=1):
            done_chunks += 1
            progress(f"Analyzing {name}, part {part} of {len(chunks)} (chunk {done_chunks} of {total_chunks})")
            in_chunk = {id(p) for p in chunk}
            other_lines = []
            for p in procedures:
                if id(p) in in_chunk:
                    continue
                rec = records[index_of[id(p)]]
                line = f"- {signature(p)}"
                if rec["summary"]:
                    line += f": {rec['summary']}"
                other_lines.append(line)
            other_names = [f"{m}.{n}" for m, names in all_signatures.items() if m != name for n in names]
            prompt = build_prompt(module, declarations, other_lines, other_names, chunk, part, len(chunks))
            try:
                data = gateway.call_json("analyzer", SYSTEM_PROMPT, prompt,
                                         validate=lambda d: schema_errors("analysis_chunk", d))
                unreachable_in_a_row = 0
            except LlmPermanentError as exc:
                raise BlockerError(str(exc)) from exc
            except (LlmTransientError, LlmSchemaError) as exc:
                if isinstance(exc, LlmTransientError):
                    unreachable_in_a_row += 1
                    if unreachable_in_a_row >= MAX_CONSECUTIVE_UNREACHABLE:
                        raise BlockerError(
                            f"The model could not be reached for {MAX_CONSECUTIVE_UNREACHABLE} chunks in a row. "
                            f"Last error: {exc}") from exc
                else:
                    unreachable_in_a_row = 0
                names = ", ".join(p.name for p in chunk[:5]) + ("..." if len(chunk) > 5 else "")
                flags.append(new_flag(
                    "CHUNK_ANALYSIS_FAILED", SEV_WARNING,
                    f"The model could not analyze part {part} of {name} ({names}). Its procedures keep default values. {exc}",
                    source_ref=f"{name}:{chunk[0].start_line}",
                    suggested_action="Run the migration again, or review these procedures by hand."))
                continue

            if not module_summary:
                module_summary = str(data.get("module_summary", "")).strip()
            matched = _match_entries(chunk, data.get("procedures", []))
            ignored = len(data.get("procedures", [])) - len(matched)
            if ignored > 0:
                flags.append(new_flag("UNKNOWN_PROCEDURE_IGNORED", SEV_INFO,
                                      f"The model returned {ignored} entr{'y' if ignored == 1 else 'ies'} for {name} "
                                      "that match no procedure in the code. They were ignored.", source_ref=name))
            for chunk_index, proc in enumerate(chunk):
                i = index_of[id(proc)]
                entry = matched.get(chunk_index)
                if entry is None:
                    flags.append(new_flag("PROCEDURE_NOT_ANALYZED", SEV_WARNING,
                                          f"The model did not return an entry for {proc.name}.",
                                          source_ref=f"{name}:{proc.start_line}"))
                    continue
                rec = records[i]
                rec.update({
                    "role": entry["role"], "summary": str(entry["summary"]).strip(),
                    "calls": _strings(entry.get("calls")), "reads": _strings(entry.get("reads")),
                    "writes": _strings(entry.get("writes")), "support": entry["support"],
                    "support_reason": str(entry["support_reason"]).strip(), "analyzed": True,
                })
                llm_constructs[i] = list(entry.get("constructs", []))

        # Rule scan and merge, for every procedure, including those the model did not return.
        for i, proc in enumerate(procedures):
            rec = records[i]
            scanned = scan_procedure(proc)
            seen = set()
            best, best_reason = rec["support"], None

            def raise_to(level, reason):
                nonlocal best, best_reason
                if level in SUPPORT_RANK and SUPPORT_RANK[level] > SUPPORT_RANK[best]:
                    best, best_reason = level, reason

            for group in _group_scanned(scanned):
                first = group[0]
                lines = [g["line"] for g in group]
                for g in group:
                    seen.add(g["line"])
                where = f" ({len(group)} places: lines {', '.join(str(n) for n in lines[:8])})" if len(group) > 1 else ""
                flags.append(_construct_flag(
                    name, first["level"], f"{first['level'].upper()}_{first['code']}",
                    f"{first['label']} in {proc.name}{where}.", first["line"], first["snippet"], first["suggested_action"]))
                raise_to(first["level"], f"{first['label']} (found by the rule check).")
            for construct in llm_constructs[i]:
                line = _line_of(construct.get("snippet", ""), proc)
                if line in seen:
                    continue
                seen.add(line)
                flags.append(_construct_flag(
                    name, construct["level"], f"{construct['level'].upper()}_CONSTRUCT",
                    f"{construct['construct']} in {proc.name}: {construct['reason']}", line,
                    construct.get("snippet", ""), construct.get("suggested_action")))
                raise_to(construct["level"], f"{construct['construct']}: {construct['reason']}")
            if best != rec["support"]:
                rec["support"] = best
                if best_reason:
                    rec["support_reason"] = best_reason
        for item in scan_declarations(module["code"], procedures):
            flags.append(_construct_flag(name, item["level"], f"{item['level'].upper()}_{item['code']}",
                                         f"{item['label']} in the declarations of {name}.", item["line"],
                                         item["snippet"], item["suggested_action"]))

        if not procedures:
            module_summary = "Declarations only. This module has no procedures."
        modules_out.append({
            "name": name, "type": module["type"], "summary": module_summary,
            "line_count": module["line_count"], "procedure_count": len(procedures),
        })
        procedures_out.extend(records)

    model = {
        "schema_version": SCHEMA_VERSION,
        "source_file": vba.get("source_file", ""),
        "modules": modules_out,
        "procedures": procedures_out,
        "flags": flags,
        "usage": {"tokens": gateway.tokens_used, "calls": gateway.calls, "chunks": total_chunks},
    }
    return model, flags


def analyzer_stage(state, ctx) -> dict:
    run_id = state["run_id"]
    ws = ctx.workspace
    source = ws.artifact_path(run_id, "vba_modules")
    if not source.is_file():
        raise BlockerError("The extracted VBA code is missing, so there is nothing to analyze.")
    vba = read_json(source)
    provider = ctx.llm_provider or create_provider(ctx.settings)
    record = ctx.run_store.read(run_id) or {}
    gateway = LlmGateway(provider, ctx.settings, log_dir=ws.logs_dir(run_id) / "llm",
                         tokens_before=record.get("tokens_used", 0))

    def progress(text: str) -> None:
        ctx.run_store.update(run_id, detail=text)

    try:
        model, flags = analyze_modules(vba, gateway, ctx.settings, progress)
    finally:
        ctx.run_store.update(run_id, detail=None)
    validate_artifact("analysis_model", model)
    out_path = ws.artifact_path(run_id, "analysis_model")
    write_json_atomic(out_path, model)
    return {"analysis_path": str(out_path), "flags": flags, "tokens_used": gateway.tokens_used}
