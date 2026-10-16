"""Pure functions that turn LLM chunk results into one clean migration spec.

Nothing here calls the LLM. The platform merges duplicates, fixes names and types, checks
source references against the analysis, and computes support levels itself.
"""
from __future__ import annotations

import re

from app.core.models import SEV_INFO, SEV_WARNING, new_flag

SUPPORT_RANK = {"supported": 0, "partial": 1, "unsupported": 2}

FIELD_TYPES = ("string", "int", "decimal", "date", "datetime", "bool")
_TYPE_MAP = {
    "string": "string", "text": "string", "str": "string", "char": "string",
    "int": "int", "integer": "int", "long": "int", "short": "int", "byte": "int", "number": "decimal",
    "decimal": "decimal", "double": "decimal", "single": "decimal", "float": "decimal", "currency": "decimal",
    "money": "decimal",
    "date": "date", "datetime": "datetime", "time": "datetime", "timestamp": "datetime",
    "bool": "bool", "boolean": "bool", "yesno": "bool",
}
CONTROL_TYPES = ("text", "number", "date", "dropdown", "checkbox", "button", "table", "label", "other")
_CONTROL_MAP = {
    "textbox": "text", "text": "text", "input": "text", "string": "text", "textarea": "text",
    "number": "number", "numeric": "number", "spinner": "number",
    "date": "date", "datepicker": "date", "datetime": "date",
    "dropdown": "dropdown", "combobox": "dropdown", "select": "dropdown", "listbox": "dropdown", "list": "dropdown",
    "checkbox": "checkbox", "boolean": "checkbox", "optionbutton": "checkbox", "radio": "checkbox",
    "button": "button", "commandbutton": "button", "submit": "button",
    "table": "table", "grid": "table", "listview": "table", "datagrid": "table",
    "label": "label", "message": "label",
}
RULE_KINDS = ("validation", "calculation", "lookup", "automation", "other")
REPORT_FORMATS = ("pdf", "csv", "xlsx", "html", "other")


# ---------- small helpers ----------
def pascal(text, fallback="Item") -> str:
    words = re.findall(r"[A-Za-z0-9]+", str(text or ""))
    name = "".join(w[:1].upper() + w[1:] for w in words)
    if not name:
        return fallback
    return name if not name[0].isdigit() else "N" + name


def norm_key(text) -> str:
    key = re.sub(r"[^a-z0-9]", "", str(text or "").lower())
    if len(key) > 3 and key.endswith("s") and not key.endswith("ss"):
        key = key[:-1]
    return key


def norm_field_type(value) -> str:
    return _TYPE_MAP.get(re.sub(r"[^a-z]", "", str(value or "").lower()), "string")


def norm_control_type(value) -> str:
    return _CONTROL_MAP.get(re.sub(r"[^a-z]", "", str(value or "").lower()), "other")


def norm_rule_kind(value) -> str:
    key = str(value or "").strip().lower()
    return key if key in RULE_KINDS else "other"


def norm_report_format(value) -> str:
    key = str(value or "").strip().lower().lstrip(".")
    key = {"excel": "xlsx", "xls": "xlsx", "text": "csv", "txt": "csv"}.get(key, key)
    return key if key in REPORT_FORMATS else "other"


def _union(*lists) -> list:
    seen, out = set(), []
    for items in lists:
        for item in items or []:
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


def _longer(a: str, b: str) -> str:
    a, b = (a or "").strip(), (b or "").strip()
    return a if len(a) >= len(b) else b


def _clean_refs(refs) -> list:
    return _union([str(r).strip() for r in (refs or []) if str(r).strip()])


# ---------- merging chunk results ----------
def merge_chunks(chunks: list) -> dict:
    """Merge the validated chunk results (in order) into one dict of element lists, without ids."""
    entities: dict = {}
    rules: dict = {}
    screens: dict = {}
    workflows: dict = {}
    reports: dict = {}
    questions: list = []

    for chunk in chunks:
        for e in chunk.get("entities", []):
            key = norm_key(e["name"])
            if not key:
                continue
            cur = entities.setdefault(key, {"name": pascal(e["name"]), "description": "", "fields": {}, "inferred": True, "source_ref": []})
            cur["description"] = _longer(cur["description"], e.get("description", ""))
            cur["inferred"] = cur["inferred"] and bool(e.get("inferred", True))
            cur["source_ref"] = _union(cur["source_ref"], _clean_refs(e.get("source_ref")))
            for f in e.get("fields", []):
                fkey = norm_key(f["name"])
                if not fkey:
                    continue
                cf = cur["fields"].setdefault(fkey, {"name": pascal(f["name"], "Field"), "type": norm_field_type(f.get("type")),
                                                     "required": False, "notes": ""})
                cf["required"] = cf["required"] or bool(f.get("required", False))
                cf["notes"] = _longer(cf["notes"], f.get("notes", ""))
        for r in chunk.get("rules", []):
            key = norm_key(r["name"])
            if not key:
                continue
            cur = rules.setdefault(key, {"name": pascal(r["name"], "Rule"), "kind": norm_rule_kind(r.get("kind")), "description": "",
                                         "inputs": [], "outputs": [], "entities": [], "source_ref": []})
            cur["description"] = _longer(cur["description"], r.get("description", ""))
            if cur["kind"] == "other":
                cur["kind"] = norm_rule_kind(r.get("kind"))
            cur["inputs"] = cur["inputs"] or [{"name": i["name"], "type": i.get("type", "")} for i in r.get("inputs", [])]
            cur["outputs"] = cur["outputs"] or [{"name": o["name"], "type": o.get("type", "")} for o in r.get("outputs", [])]
            cur["entities"] = _union(cur["entities"], [pascal(x) for x in r.get("entities", [])])
            cur["source_ref"] = _union(cur["source_ref"], _clean_refs(r.get("source_ref")))
        for s in chunk.get("screens", []):
            key = norm_key(s["name"])
            if not key:
                continue
            cur = screens.setdefault(key, {"name": pascal(s["name"], "Screen"), "purpose": "", "controls": {}, "actions": {},
                                           "entities": [], "inferred": True, "source_ref": []})
            cur["purpose"] = _longer(cur["purpose"], s.get("purpose", ""))
            cur["inferred"] = cur["inferred"] and bool(s.get("inferred", True))
            cur["entities"] = _union(cur["entities"], [pascal(x) for x in s.get("entities", [])])
            cur["source_ref"] = _union(cur["source_ref"], _clean_refs(s.get("source_ref")))
            for c in s.get("controls", []):
                ckey = norm_key(c["name"])
                if ckey:
                    cur["controls"].setdefault(ckey, {"name": pascal(c["name"], "Control"), "type": norm_control_type(c.get("type")),
                                                      "label": c.get("label", "") or "", "binds_to": c.get("binds_to", "") or ""})
            for a in s.get("actions", []):
                akey = norm_key(a["name"])
                if akey:
                    cur["actions"].setdefault(akey, {"name": pascal(a["name"], "Action"), "description": a.get("description", "") or "",
                                                     "calls": pascal(a["calls"]) if a.get("calls") else ""})
        for w in chunk.get("workflows", []):
            key = norm_key(w["name"])
            if not key:
                continue
            steps = []
            for index, step in enumerate(w.get("steps", []), start=1):
                if isinstance(step, str):
                    steps.append({"order": index, "description": step.strip(), "rule": ""})
                else:
                    steps.append({"order": index, "description": str(step.get("description", "")).strip(),
                                  "rule": pascal(step["rule"]) if step.get("rule") else ""})
            cur = workflows.setdefault(key, {"name": pascal(w["name"], "Workflow"), "description": "", "trigger": "", "steps": [], "source_ref": []})
            cur["description"] = _longer(cur["description"], w.get("description", ""))
            cur["trigger"] = cur["trigger"] or (w.get("trigger", "") or "")
            if len(steps) > len(cur["steps"]):
                cur["steps"] = steps
            cur["source_ref"] = _union(cur["source_ref"], _clean_refs(w.get("source_ref")))
        for r in chunk.get("reports", []):
            key = norm_key(r["name"])
            if not key:
                continue
            cur = reports.setdefault(key, {"name": pascal(r["name"], "Report"), "format": norm_report_format(r.get("format")),
                                           "description": "", "data_from": [], "source_ref": []})
            cur["description"] = _longer(cur["description"], r.get("description", ""))
            if cur["format"] == "other":
                cur["format"] = norm_report_format(r.get("format"))
            cur["data_from"] = _union(cur["data_from"], [pascal(x) for x in r.get("data_from", [])])
            cur["source_ref"] = _union(cur["source_ref"], _clean_refs(r.get("source_ref")))
        for q in chunk.get("open_questions", []):
            if str(q.get("text", "")).strip():
                questions.append({"text": str(q["text"]).strip(), "source_ref": _clean_refs(q.get("source_ref"))})

    for e in entities.values():
        e["fields"] = list(e["fields"].values())
    for s in screens.values():
        s["controls"] = list(s["controls"].values())
        s["actions"] = list(s["actions"].values())
    return {
        "entities": list(entities.values()), "rules": list(rules.values()), "screens": list(screens.values()),
        "workflows": list(workflows.values()), "reports": list(reports.values()), "open_questions": questions,
    }


# ---------- entity reconciliation ----------
def apply_entity_merges(parts: dict, merges: list) -> int:
    """Apply [{"canonical": ..., "aliases": [...]}] from the reconcile call. Returns merges applied."""
    by_key = {norm_key(e["name"]): e for e in parts["entities"]}
    rename = {}
    applied = 0
    for item in merges:
        canonical = by_key.get(norm_key(item.get("canonical")))
        if canonical is None:
            continue
        for alias in item.get("aliases", []):
            alias_entity = by_key.get(norm_key(alias))
            if alias_entity is None or alias_entity is canonical:
                continue
            canonical["description"] = _longer(canonical["description"], alias_entity["description"])
            canonical["inferred"] = canonical["inferred"] and alias_entity["inferred"]
            canonical["source_ref"] = _union(canonical["source_ref"], alias_entity["source_ref"])
            known = {norm_key(f["name"]) for f in canonical["fields"]}
            for field in alias_entity["fields"]:
                if norm_key(field["name"]) not in known:
                    canonical["fields"].append(field)
            rename[norm_key(alias_entity["name"])] = canonical["name"]
            alias_entity["_gone"] = True
            applied += 1
    parts["entities"] = [e for e in parts["entities"] if not e.get("_gone")]
    if rename:
        def fix(names):
            return _union([rename.get(norm_key(n), n) for n in names])
        for rule in parts["rules"]:
            rule["entities"] = fix(rule["entities"])
        for screen in parts["screens"]:
            screen["entities"] = fix(screen["entities"])
        for report in parts["reports"]:
            report["data_from"] = fix(report["data_from"])
    return applied


# ---------- finishing ----------
def finish_spec(parts: dict, analysis: dict, source_file: str, usage: dict, flags: list) -> dict:
    """Validate references, link entity names, compute support, assign ids, add stubs."""
    procedures = {p["id"]: p for p in analysis["procedures"]}
    modules = {m["name"] for m in analysis["modules"]}
    entity_names = {norm_key(e["name"]): e["name"] for e in parts["entities"]}

    def check_refs(kind: str, element: dict) -> None:
        valid = [r for r in element["source_ref"] if r in procedures or r in modules]
        dropped = len(element["source_ref"]) - len(valid)
        element["source_ref"] = valid
        if dropped:
            flags.append(new_flag("SPEC_UNKNOWN_REFERENCE", SEV_INFO,
                                  f"{kind} {element['name']}: {dropped} source reference(s) did not match any procedure and were removed."))
        if not valid:
            flags.append(new_flag("SPEC_ELEMENT_UNTRACED", SEV_WARNING,
                                  f"{kind} {element['name']} has no valid source reference, so it cannot be traced to the VBA code.",
                                  suggested_action="Check this item by hand before relying on it."))
        weakest = "supported" if valid else "partial"
        for ref in valid:
            level = procedures[ref]["support"] if ref in procedures else "supported"
            if SUPPORT_RANK[level] > SUPPORT_RANK[weakest]:
                weakest = level
        element["support"] = weakest

    def link(names) -> list:
        return _union([entity_names[norm_key(n)] for n in names if norm_key(n) in entity_names])

    entities, rules, screens, workflows, reports = [], [], [], [], []
    for i, e in enumerate(parts["entities"], start=1):
        item = {"id": f"ENT-{i:03d}", "name": e["name"], "description": e["description"], "fields": e["fields"],
                "inferred": e["inferred"], "source_ref": list(e["source_ref"])}
        check_refs("Entity", item)
        entities.append(item)
    for i, r in enumerate(parts["rules"], start=1):
        item = {"id": f"RUL-{i:03d}", "name": r["name"], "kind": r["kind"], "description": r["description"],
                "inputs": r["inputs"], "outputs": r["outputs"], "entities": link(r["entities"]), "source_ref": list(r["source_ref"])}
        check_refs("Rule", item)
        rules.append(item)
    rule_names = {norm_key(r["name"]): r["name"] for r in rules}
    for i, s in enumerate(parts["screens"], start=1):
        actions = [{**a, "calls": rule_names.get(norm_key(a["calls"]), a["calls"])} for a in s["actions"]]
        item = {"id": f"SCR-{i:03d}", "name": s["name"], "purpose": s["purpose"], "controls": s["controls"], "actions": actions,
                "entities": link(s["entities"]), "inferred": s["inferred"], "source_ref": list(s["source_ref"])}
        check_refs("Screen", item)
        screens.append(item)
    for i, w in enumerate(parts["workflows"], start=1):
        steps = [{**s, "rule": rule_names.get(norm_key(s["rule"]), s["rule"])} for s in w["steps"]]
        item = {"id": f"WFL-{i:03d}", "name": w["name"], "description": w["description"], "trigger": w["trigger"],
                "steps": steps, "source_ref": list(w["source_ref"])}
        check_refs("Workflow", item)
        workflows.append(item)
    for i, r in enumerate(parts["reports"], start=1):
        item = {"id": f"RPT-{i:03d}", "name": r["name"], "format": r["format"], "description": r["description"],
                "data_from": link(r["data_from"]), "source_ref": list(r["source_ref"])}
        check_refs("Report", item)
        reports.append(item)

    for q in parts["open_questions"]:
        refs = [r for r in q["source_ref"] if r in procedures or r in modules]
        flags.append(new_flag("SPEC_OPEN_QUESTION", SEV_WARNING, q["text"], source_ref=refs[0] if refs else None,
                              suggested_action="Decide this by hand. The model did not guess."))

    stubs = []
    for p in analysis["procedures"]:
        if p["support"] != "supported":
            stubs.append({"procedure_id": p["id"], "module": p["module"], "name": p["name"], "start_line": p["start_line"],
                          "end_line": p["end_line"], "level": p["support"], "reason": p["support_reason"]})

    return {
        "schema_version": "1.0",
        "source_file": source_file,
        "notes": [
            "Only the VBA code was analyzed. Workbook data, cell contents and UserForm layouts were not available.",
            "Entities, fields and screen controls are inferred from how the code uses sheets, ranges, forms and message boxes.",
            "Every element lists the procedures it came from in source_ref.",
        ],
        "entities": entities, "rules": rules, "screens": screens, "workflows": workflows, "reports": reports,
        "stubs": stubs, "flags": flags, "usage": usage,
    }
