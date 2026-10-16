"""Turn the migration spec into a concrete generation plan: class names, method signatures, stubs.

Everything the pages and the LLM must agree on (names, parameter lists, return types) is decided
here by the platform, so generated files fit together even though the LLM only writes method bodies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.plugins.xlsm_to_aspnetcore.gen.csharp import (
    MEMBER_RESERVED, class_name, cs_type, member_name, param_name, unique,
)
from app.plugins.xlsm_to_aspnetcore.spec_merge import norm_field_type, norm_key, pascal

SUPPORT_RANK = {"supported": 0, "partial": 1, "unsupported": 2}
RESERVED_PAGE_NAMES = {"Index", "Reports", "Workflows", "Entities", "Shared", "Error"}
RULES_RESERVED = {"Repo", "ExportFolder", "BusinessRules"} | MEMBER_RESERVED
STUB_REPORT_FORMATS = {
    "pdf": "PDF export needs a .NET PDF library such as QuestPDF. Add the package and implement this report.",
    "xlsx": "Excel export needs a library such as ClosedXML. Add the package and implement this report.",
}


@dataclass
class PField:
    spec_name: str
    name: str
    cs_type: str
    default: str   # C# initializer text, or ""


@dataclass
class PEntity:
    spec: dict
    cls: str
    fields: list


@dataclass
class PMethod:
    id: str
    kind: str                  # rule | workflow | report
    name: str
    spec: dict
    params: list               # [(cs_type, cs_name, spec_name)]
    returns: str
    sources: list
    support: str
    stub_reason: str | None = None   # set when the platform writes a stub instead of the LLM

    @property
    def signature(self) -> str:
        args = ", ".join(f"{t} {n}" for t, n, _s in self.params)
        return f"public {self.returns} {self.name}({args})"


@dataclass
class PProp:
    spec_name: str
    name: str
    cs_type: str
    control_type: str
    label: str


@dataclass
class PAction:
    spec: dict
    handler: str
    rule: PMethod | None


@dataclass
class PScreen:
    spec: dict
    cls: str
    props: list
    actions: list


@dataclass
class Plan:
    app: str
    title: str
    entities: list = field(default_factory=list)
    rules: list = field(default_factory=list)
    workflows: list = field(default_factory=list)
    reports: list = field(default_factory=list)
    screens: list = field(default_factory=list)

    @property
    def methods(self) -> list:
        return self.rules + self.workflows + self.reports

    @property
    def entity_classes(self) -> dict:
        return {norm_key(e.spec["name"]): e.cls for e in self.entities}


def app_name(source_file: str, taken: set) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", str(source_file or "")).strip()
    base = pascal(stem, "MigratedApp")
    if base in taken or base in {"Models", "Services", "Infrastructure", "Pages", "System", "Microsoft"}:
        base += "App"
    return base


def stub_reason_for(element: dict, stubs: list) -> str:
    by_id = {s["procedure_id"]: s for s in stubs}
    reasons = [by_id[r]["reason"] for r in element["source_ref"] if r in by_id and by_id[r]["level"] == "unsupported"]
    return " ".join(dict.fromkeys(reasons)) or "The source code uses a feature that cannot be migrated."


def build_plan(spec: dict) -> Plan:
    names_taken = {pascal(e["name"]) for e in spec["entities"]}
    plan = Plan(app=app_name(spec["source_file"], names_taken), title=re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", app_name(spec["source_file"], names_taken)))

    class_taken: set = set()
    for e in spec["entities"]:
        cls = unique(class_name(e["name"]), class_taken)
        taken = {"Id"}
        fields = []
        for f in e["fields"]:
            ftype = norm_field_type(f["type"])
            if norm_key(f["name"]) == "id":
                if ftype == "int":
                    continue
                prop = unique(f"{cls}Code", taken)
            else:
                prop = member_name(f["name"], cls, taken)
            cs = {"string": "string", "int": "int", "decimal": "decimal", "date": "DateTime", "datetime": "DateTime", "bool": "bool"}[ftype]
            fields.append(PField(f["name"], prop, cs, ' = "";' if cs == "string" else ""))
        plan.entities.append(PEntity(e, cls, fields))
    classes = plan.entity_classes

    method_names: set = set()

    def make_params(inputs):
        taken, out = set(), []
        for item in inputs:
            out.append((cs_type(item.get("type", ""), classes), param_name(item["name"], taken), item["name"]))
        return out

    def returns_of(outputs):
        if not outputs:
            return "void"
        if len(outputs) == 1:
            return cs_type(outputs[0].get("type", ""), classes)
        taken: set = set()
        parts = [f"{cs_type(o.get('type', ''), classes)} {member_name(o['name'], '', taken)}" for o in outputs]
        return "(" + ", ".join(parts) + ")"

    for r in spec["rules"]:
        name = unique(r["name"], method_names, RULES_RESERVED)
        m = PMethod(r["id"], "rule", name, r, make_params(r["inputs"]), returns_of(r["outputs"]), r["source_ref"], r["support"])
        if r["support"] == "unsupported":
            m.stub_reason = stub_reason_for(r, spec["stubs"])
        plan.rules.append(m)
    for w in spec["workflows"]:
        name = unique(w["name"] if w["name"].endswith("Workflow") else w["name"] + "Workflow", method_names, RULES_RESERVED)
        m = PMethod(w["id"], "workflow", name, w, [], "string", w["source_ref"], w["support"])
        if w["support"] == "unsupported":
            m.stub_reason = stub_reason_for(w, spec["stubs"])
        plan.workflows.append(m)
    for rp in spec["reports"]:
        name = unique(rp["name"] if rp["name"].endswith("Report") else rp["name"] + "Report", method_names, RULES_RESERVED)
        m = PMethod(rp["id"], "report", name, rp, [], "ReportFile", rp["source_ref"], rp["support"])
        if rp["format"] in STUB_REPORT_FORMATS:
            m.stub_reason = STUB_REPORT_FORMATS[rp["format"]]
        elif rp["support"] == "unsupported":
            m.stub_reason = stub_reason_for(rp, spec["stubs"])
        plan.reports.append(m)

    rule_by_key = {norm_key(m.spec["name"]): m for m in plan.rules}
    screen_classes: set = set()
    for s in spec["screens"]:
        base = pascal(s["name"], "Screen")
        if base in RESERVED_PAGE_NAMES:
            base += "Screen"
        cls = unique(base, screen_classes)
        taken: set = set()
        props = []
        for c in s["controls"]:
            if c["type"] in ("button", "label", "table"):
                continue
            cs = {"number": "decimal", "date": "DateTime", "checkbox": "bool"}.get(c["type"], "string")
            props.append(PProp(c["name"], member_name(c["name"], "", taken), cs, c["type"], c["label"] or c["name"]))
        handlers: set = set()
        actions = []
        for a in s["actions"]:
            actions.append(PAction(a, unique(pascal(a["name"], "Run"), handlers), rule_by_key.get(norm_key(a["calls"])) if a["calls"] else None))
        plan.screens.append(PScreen(s, cls, props, actions))
    return plan
