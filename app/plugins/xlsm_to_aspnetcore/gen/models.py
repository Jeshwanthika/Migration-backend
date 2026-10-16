"""Entity classes and empty data files (FR-GN2). No workbook data is carried over."""
from __future__ import annotations

from app.plugins.xlsm_to_aspnetcore.gen.csharp import comment_text


def entity_source(app: str, e) -> str:
    spec = e.spec
    lines = [
        f"namespace {app}.Models;",
        "",
        f"// {spec['id']} {comment_text(spec['name'])} ({'inferred' if spec['inferred'] else 'explicit in the VBA code'})",
    ]
    if spec["description"]:
        lines.append(f"// {comment_text(spec['description'])}")
    lines.append(f"// Source: {', '.join(spec['source_ref']) or 'none'}")
    lines += [f"public class {e.cls} : IEntity", "{", "    public int Id { get; set; }"]
    for f in e.fields:
        lines.append(f"    public {f.cs_type} {f.name} {{ get; set; }}{f.default}")
    lines += ["}", ""]
    return "\n".join(lines)


def entity_files(app: str, plan) -> dict:
    files = {}
    for e in plan.entities:
        files[f"{app}/Models/{e.cls}.cs"] = entity_source(app, e)
        files[f"{app}/Data/{e.cls}.json"] = "[]\n"
    return files
