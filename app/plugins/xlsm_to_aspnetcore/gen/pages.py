"""Razor Pages written by the platform from the plan: home, entity lists, screens, workflows, reports.

Pages are thin. They collect input and call the business-rule methods whose signatures the plan
fixed. The LLM never writes a page.
"""
from __future__ import annotations

from app.plugins.xlsm_to_aspnetcore.gen.csharp import comment_text, razor_text
from app.plugins.xlsm_to_aspnetcore.spec_merge import norm_key

USINGS = """using System.ComponentModel.DataAnnotations;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using {app}.Infrastructure;
using {app}.Models;
using {app}.Services;
"""


def _usings(app: str) -> str:
    return USINGS.replace("{app}", app)


def nav_links(plan) -> list:
    links = [("Home", "/Index")]
    links += [(e.spec["name"], f"/Entities/{e.cls}") for e in plan.entities]
    links += [(s.spec["name"], f"/{s.cls}") for s in plan.screens]
    if plan.workflows:
        links.append(("Workflows", "/Workflows"))
    if plan.reports:
        links.append(("Reports", "/Reports"))
    return links


# ---------- entity pages ----------
def entity_page_files(app: str, plan) -> dict:
    files = {}
    for e in plan.entities:
        cls = e.cls
        model = [
            _usings(app) + f"\nnamespace {app}.Pages.Entities;\n",
            f"public class {cls}Model : PageModel",
            "{",
            f"    private readonly IRepository<{cls}> _repo;",
            "",
            f"    public {cls}Model(IRepository<{cls}> repo)",
            "    {",
            "        _repo = repo;",
            "    }",
            "",
            f"    [BindProperty] public {cls} Item {{ get; set; }} = new();",
            f"    public IReadOnlyList<{cls}> Items {{ get; set; }} = new List<{cls}>();",
            "",
            "    public void OnGet()",
            "    {",
            "        Items = _repo.GetAll();",
            "    }",
            "",
            "    public IActionResult OnPostAdd()",
            "    {",
            "        Item.Id = 0;",
            "        _repo.Add(Item);",
            "        return RedirectToPage();",
            "    }",
            "",
            "    public IActionResult OnPostDelete(int id)",
            "    {",
            "        _repo.Delete(id);",
            "        return RedirectToPage();",
            "    }",
            "}",
            "",
        ]
        view = ["@page", f"@model {cls}Model", "@{", f'    ViewData["Title"] = "{razor_text(e.spec["name"])}";', "}", "",
                f"<h1>{razor_text(e.spec['name'])}</h1>"]
        if e.spec["description"]:
            view.append(f'<p class="muted">{razor_text(e.spec["description"])}</p>')
        view += ["", "<table>", "    <thead>", "        <tr>", "            <th>Id</th>"]
        view += [f"            <th>{razor_text(f.name)}</th>" for f in e.fields]
        view += ["            <th></th>", "        </tr>", "    </thead>", "    <tbody>", "        @foreach (var row in Model.Items)",
                 "        {", "            <tr>", "                <td>@row.Id</td>"]
        for f in e.fields:
            if f.cs_type == "DateTime":
                view.append(f'                <td>@row.{f.name}.ToString("yyyy-MM-dd")</td>')
            elif f.cs_type == "bool":
                view.append(f'                <td>@(row.{f.name} ? "yes" : "no")</td>')
            else:
                view.append(f"                <td>@row.{f.name}</td>")
        view += ["                <td>",
                 '                    <form method="post" asp-page-handler="Delete" asp-route-id="@row.Id">',
                 "                        <button type=\"submit\">Delete</button>", "                    </form>",
                 "                </td>", "            </tr>", "        }", "    </tbody>", "</table>",
                 "@if (!Model.Items.Any())", "{", '    <p class="muted">No records yet.</p>', "}"]
        if e.fields:
            view += ["", "<h2>Add a record</h2>", '<form method="post" asp-page-handler="Add">']
            for f in e.fields:
                view.append(f'    <label asp-for="Item.{f.name}">{razor_text(f.spec_name)}</label>')
                if f.cs_type == "DateTime":
                    view.append(f'    <input asp-for="Item.{f.name}" type="date" />')
                else:
                    view.append(f'    <input asp-for="Item.{f.name}" />')
            view += ['    <button type="submit">Add</button>', "</form>"]
        files[f"{app}/Pages/Entities/{cls}.cshtml.cs"] = "\n".join(model)
        files[f"{app}/Pages/Entities/{cls}.cshtml"] = "\n".join(view) + "\n"
    return files


# ---------- screens ----------
def _call_args(plan, screen, rule) -> tuple:
    """Return (argument expressions, notes) for calling a rule from a screen."""
    by_key = {norm_key(p.spec_name): p for p in screen.props}
    entity_by_class = {e.cls: e for e in plan.entities}
    args, notes = [], []
    for ptype, _pname, spec_name in rule.params:
        prop = by_key.get(norm_key(spec_name))
        if prop is not None:
            args.append(f"Input.{prop.name}" if prop.cs_type == ptype else f"Coerce.To<{ptype}>(Input.{prop.name})")
        elif ptype in entity_by_class:
            sets = []
            for f in entity_by_class[ptype].fields:
                p = by_key.get(norm_key(f.spec_name))
                if p is not None:
                    sets.append(f"{f.name} = " + (f"Input.{p.name}" if p.cs_type == f.cs_type else f"Coerce.To<{f.cs_type}>(Input.{p.name})"))
            args.append(f"new {ptype} {{ {', '.join(sets)} }}" if sets else f"new {ptype}()")
        elif ptype.startswith("List<"):
            args.append(f"new {ptype}()")
        else:
            args.append(f"default({ptype})!" if ptype == "string" else f"default({ptype})")
            notes.append(f"MIGRATION-TODO: no control supplies '{comment_text(spec_name)}'")
    return args, notes


def screen_files(app: str, plan) -> dict:
    files = {}
    for s in plan.screens:
        spec = s.spec
        lines = [_usings(app) + f"\nnamespace {app}.Pages;\n", f"public class {s.cls}Model : PageModel", "{",
                 "    private readonly BusinessRules _rules;", "", f"    public {s.cls}Model(BusinessRules rules)",
                 "    {", "        _rules = rules;", "    }", "", "    [BindProperty] public InputModel Input { get; set; } = new();",
                 '    public string Message { get; set; } = "";', '    public string ResultText { get; set; } = "";', "",
                 "    public class InputModel", "    {"]
        for p in s.props:
            if p.cs_type == "DateTime":
                lines += ["        [DataType(DataType.Date)]",
                          '        [DisplayFormat(DataFormatString = "{0:yyyy-MM-dd}", ApplyFormatInEditMode = true)]',
                          f"        public DateTime {p.name} {{ get; set; }} = DateTime.Today;"]
            elif p.cs_type == "string":
                lines.append(f'        public string {p.name} {{ get; set; }} = "";')
            else:
                lines.append(f"        public {p.cs_type} {p.name} {{ get; set; }}")
        lines += ["    }", "", "    public void OnGet()", "    {", "    }"]
        for a in s.actions:
            lines += ["", f"    public IActionResult OnPost{a.handler}()", "    {", "        try", "        {"]
            if a.rule is None:
                lines.append(f'            Message = "MIGRATION-TODO: the action {a.handler} has no migrated logic yet.";')
            else:
                args, notes = _call_args(plan, s, a.rule)
                lines += [f"            // {n}" for n in notes]
                call = f"_rules.{a.rule.name}({', '.join(args)})"
                if a.rule.returns == "void":
                    lines += [f"            {call};", f'            Message = "{a.handler} completed.";']
                else:
                    lines += [f"            var result = {call};", f'            Message = "{a.handler} completed.";',
                              "            ResultText = ResultFormatter.Format(result);"]
            lines += ["        }", "        catch (NotImplementedException ex)", "        {", "            Message = ex.Message;", "        }",
                      "        catch (Exception ex)", "        {", '            Message = "Something went wrong: " + ex.Message;', "        }",
                      "        return Page();", "    }"]
        lines += ["}", ""]
        view = ["@page", f"@model {s.cls}Model", "@{", f'    ViewData["Title"] = "{razor_text(spec["name"])}";', "}", "",
                f"<h1>{razor_text(spec['name'])}</h1>"]
        if spec["purpose"]:
            view.append(f'<p class="muted">{razor_text(spec["purpose"])}</p>')
        view += ["@if (!string.IsNullOrEmpty(Model.Message))", "{", '    <div class="message">@Model.Message</div>', "}", "",
                 '<form method="post">']
        for p in s.props:
            view.append(f'    <label asp-for="Input.{p.name}">{razor_text(p.label)}</label>')
            view.append(f'    <input asp-for="Input.{p.name}" type="date" />' if p.cs_type == "DateTime" else f'    <input asp-for="Input.{p.name}" />')
        if s.actions:
            for a in s.actions:
                title = f' title="{razor_text(a.spec["description"])}"' if a.spec["description"] else ""
                view.append(f'    <button type="submit" asp-page-handler="{a.handler}"{title}>{razor_text(a.spec["name"])}</button>')
        else:
            view.append('    <p class="muted">No actions were identified for this screen.</p>')
        view += ["</form>", "", "@if (!string.IsNullOrEmpty(Model.ResultText))", "{", "    <pre>@Model.ResultText</pre>", "}"]
        files[f"{app}/Pages/{s.cls}.cshtml.cs"] = "\n".join(lines)
        files[f"{app}/Pages/{s.cls}.cshtml"] = "\n".join(view) + "\n"
    return files


# ---------- workflows and reports ----------
def workflows_files(app: str, plan) -> dict:
    if not plan.workflows:
        return {}
    lines = [_usings(app) + f"\nnamespace {app}.Pages;\n", "public class WorkflowsModel : PageModel", "{",
             "    private readonly BusinessRules _rules;", "", "    public WorkflowsModel(BusinessRules rules)", "    {", "        _rules = rules;", "    }", "",
             '    public string Message { get; set; } = "";', '    public string ResultText { get; set; } = "";', "", "    public void OnGet()", "    {", "    }"]
    handler_names = {}
    for w in plan.workflows:
        handler = w.name
        handler_names[w.id] = handler
        lines += ["", f"    public IActionResult OnPost{handler}()", "    {", "        try", "        {",
                  f"            ResultText = ResultFormatter.Format(_rules.{w.name}());", f'            Message = "{handler} finished.";',
                  "        }", "        catch (NotImplementedException ex)", "        {", "            Message = ex.Message;", "        }",
                  "        catch (Exception ex)", "        {", '            Message = "Something went wrong: " + ex.Message;', "        }",
                  "        return Page();", "    }"]
    lines += ["}", ""]
    view = ["@page", "@model WorkflowsModel", "@{", '    ViewData["Title"] = "Workflows";', "}", "", "<h1>Workflows</h1>",
            "@if (!string.IsNullOrEmpty(Model.Message))", "{", '    <div class="message">@Model.Message</div>', "}",
            "@if (!string.IsNullOrEmpty(Model.ResultText))", "{", "    <pre>@Model.ResultText</pre>", "}"]
    for w in plan.workflows:
        spec = w.spec
        view += ["", f"<h2>{razor_text(spec['name'])}</h2>"]
        if spec["description"]:
            view.append(f"<p>{razor_text(spec['description'])}</p>")
        if spec["trigger"]:
            view.append(f'<p class="muted">Started in the workbook by: {razor_text(spec["trigger"])}</p>')
        if spec["steps"]:
            view.append("<ol>")
            view += [f"    <li>{razor_text(st['description'])}</li>" for st in spec["steps"]]
            view.append("</ol>")
        view += ['<form method="post">', f'    <button type="submit" asp-page-handler="{handler_names[w.id]}">Run</button>', "</form>"]
    return {f"{app}/Pages/Workflows.cshtml.cs": "\n".join(lines), f"{app}/Pages/Workflows.cshtml": "\n".join(view) + "\n"}


def reports_files(app: str, plan) -> dict:
    if not plan.reports:
        return {}
    lines = [_usings(app) + f"\nnamespace {app}.Pages;\n", "public class ReportsModel : PageModel", "{",
             "    private readonly BusinessRules _rules;", "", "    public ReportsModel(BusinessRules rules)", "    {", "        _rules = rules;", "    }", "",
             '    public string Message { get; set; } = "";', "", "    public void OnGet()", "    {", "    }"]
    for r in plan.reports:
        lines += ["", f"    public IActionResult OnGet{r.name}()", "    {", "        try", "        {",
                  f"            var file = _rules.{r.name}();", "            return File(file.Content, file.ContentType, file.FileName);", "        }",
                  "        catch (NotImplementedException ex)", "        {", "            Message = ex.Message;", "        }",
                  "        catch (Exception ex)", "        {", '            Message = "Something went wrong: " + ex.Message;', "        }",
                  "        return Page();", "    }"]
    lines += ["}", ""]
    view = ["@page", "@model ReportsModel", "@{", '    ViewData["Title"] = "Reports";', "}", "", "<h1>Reports and exports</h1>",
            "@if (!string.IsNullOrEmpty(Model.Message))", "{", '    <div class="message todo">@Model.Message</div>', "}"]
    for r in plan.reports:
        spec = r.spec
        view += ["", f"<h2>{razor_text(spec['name'])} <span class=\"muted\">({razor_text(spec['format'])})</span></h2>"]
        if spec["description"]:
            view.append(f"<p>{razor_text(spec['description'])}</p>")
        view.append(f'<a class="button" asp-page="/Reports" asp-page-handler="{r.name}">Download</a>')
    return {f"{app}/Pages/Reports.cshtml.cs": "\n".join(lines), f"{app}/Pages/Reports.cshtml": "\n".join(view) + "\n"}


# ---------- home ----------
def index_files(app: str, plan, spec: dict) -> dict:
    model = [_usings(app) + f"\nnamespace {app}.Pages;\n", "public class IndexModel : PageModel", "{", "    public void OnGet()", "    {", "    }", "}", ""]
    view = ["@page", "@model IndexModel", "@{", f'    ViewData["Title"] = "Home";', "}", "", f"<h1>{razor_text(plan.title)}</h1>",
            f"<p class=\"muted\">Migrated from <code>{razor_text(spec['source_file'])}</code>. Only the VBA logic was migrated. No workbook data was carried over.</p>",
            "", "<ul>"]
    for e in plan.entities:
        view.append(f'    <li>Records: <a asp-page="/Entities/{e.cls}">{razor_text(e.spec["name"])}</a></li>')
    for s in plan.screens:
        view.append(f'    <li>Screen: <a asp-page="/{s.cls}">{razor_text(s.spec["name"])}</a></li>')
    if plan.workflows:
        view.append('    <li><a asp-page="/Workflows">Workflows</a></li>')
    if plan.reports:
        view.append('    <li><a asp-page="/Reports">Reports and exports</a></li>')
    view.append("</ul>")
    if spec["stubs"]:
        view += ["", "<h2>Still to do</h2>", "<table>", "    <thead><tr><th>Procedure</th><th>Level</th><th>Why</th></tr></thead>", "    <tbody>"]
        for st in spec["stubs"]:
            view.append(f"        <tr><td>{razor_text(st['procedure_id'])}</td><td>{razor_text(st['level'])}</td><td>{razor_text(st['reason'])}</td></tr>")
        view += ["    </tbody>", "</table>"]
    return {f"{app}/Pages/Index.cshtml.cs": "\n".join(model), f"{app}/Pages/Index.cshtml": "\n".join(view) + "\n"}
