"""Render migration_spec.json as a readable Markdown document (FR-SP4)."""
from __future__ import annotations


def _cell(text) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def _refs(refs) -> str:
    return ", ".join(f"`{r}`" for r in refs) or "none"


def render_spec_markdown(spec: dict) -> str:
    out = [f"# Migration specification", "", f"Source: `{spec['source_file']}`", ""]
    for note in spec["notes"]:
        out.append(f"> {note}")
    out.append("")
    out.append(f"{len(spec['entities'])} entities, {len(spec['rules'])} rules, {len(spec['screens'])} screens, "
               f"{len(spec['workflows'])} workflows, {len(spec['reports'])} reports, {len(spec['stubs'])} procedures needing attention.")
    out.append("")

    out += ["## Entities", ""]
    if not spec["entities"]:
        out += ["None found.", ""]
    for e in spec["entities"]:
        tag = "inferred" if e["inferred"] else "explicit in the code"
        out += [f"### {e['id']} {e['name']} ({tag}, {e['support']})", "", e["description"] or "", ""]
        if e["fields"]:
            out += ["| Field | Type | Required | Notes |", "|---|---|---|---|"]
            out += [f"| {_cell(f['name'])} | {f['type']} | {'yes' if f['required'] else 'no'} | {_cell(f['notes'])} |" for f in e["fields"]]
            out.append("")
        out += [f"Source: {_refs(e['source_ref'])}", ""]

    out += ["## Business rules", ""]
    if not spec["rules"]:
        out += ["None found.", ""]
    for r in spec["rules"]:
        out += [f"### {r['id']} {r['name']} ({r['kind']}, {r['support']})", "", r["description"] or "", ""]
        if r["inputs"]:
            out.append("Inputs: " + ", ".join(f"{i['name']} ({i['type'] or '?'})" for i in r["inputs"]))
        if r["outputs"]:
            out.append("Outputs: " + ", ".join(f"{o['name']} ({o['type'] or '?'})" for o in r["outputs"]))
        if r["entities"]:
            out.append("Entities: " + ", ".join(r["entities"]))
        out += ["", f"Source: {_refs(r['source_ref'])}", ""]

    out += ["## Screens", ""]
    if not spec["screens"]:
        out += ["None found.", ""]
    for s in spec["screens"]:
        tag = "inferred" if s["inferred"] else "explicit in the code"
        out += [f"### {s['id']} {s['name']} ({tag}, {s['support']})", "", s["purpose"] or "", ""]
        if s["controls"]:
            out += ["| Control | Type | Label | Bound to |", "|---|---|---|---|"]
            out += [f"| {_cell(c['name'])} | {c['type']} | {_cell(c['label'])} | {_cell(c['binds_to'])} |" for c in s["controls"]]
            out.append("")
        for a in s["actions"]:
            call = f" (uses {a['calls']})" if a["calls"] else ""
            out.append(f"- Action **{a['name']}**{call}: {a['description']}")
        if s["actions"]:
            out.append("")
        out += [f"Source: {_refs(s['source_ref'])}", ""]

    out += ["## Workflows", ""]
    if not spec["workflows"]:
        out += ["None found.", ""]
    for w in spec["workflows"]:
        out += [f"### {w['id']} {w['name']} ({w['support']})", "", w["description"] or "", ""]
        if w["trigger"]:
            out += [f"Trigger: {w['trigger']}", ""]
        for step in w["steps"]:
            rule = f" [{step['rule']}]" if step["rule"] else ""
            out.append(f"{step['order']}. {step['description']}{rule}")
        out += ["", f"Source: {_refs(w['source_ref'])}", ""]

    out += ["## Reports and exports", ""]
    if not spec["reports"]:
        out += ["None found.", ""]
    for r in spec["reports"]:
        out += [f"### {r['id']} {r['name']} ({r['format']}, {r['support']})", "", r["description"] or "", ""]
        if r["data_from"]:
            out += ["Data from: " + ", ".join(r["data_from"]), ""]
        out += [f"Source: {_refs(r['source_ref'])}", ""]

    out += ["## Procedures that need attention", ""]
    if not spec["stubs"]:
        out += ["None. Every procedure is fully supported.", ""]
    else:
        out += ["| Procedure | Lines | Level | Reason |", "|---|---|---|---|"]
        out += [f"| `{s['procedure_id']}` | {s['start_line']}-{s['end_line']} | {s['level']} | {_cell(s['reason'])} |" for s in spec["stubs"]]
        out.append("")

    out += ["## Flags", ""]
    flags = [f for f in spec["flags"] if f["severity"] != "Info"]
    if not flags:
        out += ["No warnings.", ""]
    for f in flags:
        ref = f" (`{f['source_ref']}`)" if f.get("source_ref") else ""
        out.append(f"- **{f['severity']}** {f['code']}{ref}: {f['reason']}")
    out.append("")
    return "\n".join(out).replace("\n\n\n", "\n\n")
