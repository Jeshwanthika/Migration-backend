import json
import re
import tempfile
import unittest
from pathlib import Path

from app.core.context import PluginContext
from app.core.errors import BlockerError
from app.core.llm import LlmGateway, LlmPermanentError, LlmTransientError
from app.core.run_store import RunStore
from app.core.schema_validation import validate_artifact
from app.core.workspace import Workspace, new_run_id
from app.plugins.xlsm_to_aspnetcore.gen.csharp import (
    braces_balanced, check_body, class_name, cs_string, cs_type, param_name, razor_text,
)
from app.plugins.xlsm_to_aspnetcore.gen.pages import screen_files
from app.plugins.xlsm_to_aspnetcore.gen.plan import build_plan
from app.plugins.xlsm_to_aspnetcore.gen.scaffold import scaffold_files
from app.plugins.xlsm_to_aspnetcore.generator import FileSet, generate_app, generator_stage, write_app
from tests.fakes import FakeProvider, fake_settings

VBA_CODE = '''Attribute VB_Name = "modExp"
Option Explicit
Sub AddExpense(amt As Double, cat As String)
    Dim r As Long
    r = 2
    Cells(r, 1).Value = amt
End Sub
Function TotalFor(cat As String) As Double
    TotalFor = 0
End Function
Sub Import()
    Call AddExpense(1, "a")
End Sub
Sub MakePdf()
    ws.ExportAsFixedFormat Type:=xlTypePDF
End Sub
Sub MakeCsv()
    Open p For Output As #1
End Sub
Sub Beep()
    SendKeys "{ENTER}"
End Sub'''


def procs():
    names = [("AddExpense", 3, 7, "supported"), ("TotalFor", 8, 10, "supported"), ("Import", 11, 13, "supported"),
             ("MakePdf", 14, 16, "unsupported"), ("MakeCsv", 17, 19, "partial"), ("Beep", 20, 22, "unsupported")]
    return [{"id": f"modExp.{n}", "module": "modExp", "name": n, "kind": "Function" if n == "TotalFor" else "Sub", "scope": "Public",
             "params": [], "returns": None, "start_line": a, "end_line": b, "role": "utility", "summary": f"{n} summary",
             "calls": [], "reads": [], "writes": [], "support": s, "support_reason": f"{n} reason", "analyzed": True}
            for n, a, b, s in names]


VBA = {"source_file": "Expense Tracker.xlsm", "findings": [], "flags": [],
       "modules": [{"name": "modExp", "type": "standard", "stream": "", "line_count": 22, "code": VBA_CODE}]}
ANALYSIS = {"schema_version": "1.0", "source_file": "Expense Tracker.xlsm",
            "modules": [{"name": "modExp", "type": "standard", "summary": "", "line_count": 22, "procedure_count": 6}],
            "procedures": procs(), "flags": [], "usage": {"tokens": 0, "calls": 0, "chunks": 0}}


def spec():
    s = {
        "schema_version": "1.0", "source_file": "Expense Tracker.xlsm", "notes": [],
        "entities": [
            {"id": "ENT-001", "name": "Expense", "description": "An expense", "inferred": True, "source_ref": ["modExp.AddExpense"], "support": "supported",
             "fields": [{"name": "Id", "type": "int", "required": True, "notes": ""}, {"name": "Amount", "type": "decimal", "required": True, "notes": ""},
                        {"name": "Category", "type": "string", "required": False, "notes": ""}, {"name": "Date", "type": "date", "required": False, "notes": ""},
                        {"name": "Paid", "type": "bool", "required": False, "notes": ""}]}],
        "rules": [
            {"id": "RUL-001", "name": "AddExpense", "kind": "automation", "description": "Adds an expense", "entities": ["Expense"],
             "inputs": [{"name": "amount", "type": "decimal"}, {"name": "category", "type": "string"}], "outputs": [{"name": "saved", "type": "bool"}],
             "source_ref": ["modExp.AddExpense"], "support": "supported"},
            {"id": "RUL-002", "name": "TotalFor", "kind": "calculation", "description": "Totals", "entities": ["Expense"],
             "inputs": [{"name": "category", "type": "string"}], "outputs": [{"name": "total", "type": "decimal"}],
             "source_ref": ["modExp.TotalFor"], "support": "supported"},
            {"id": "RUL-003", "name": "PressKeys", "kind": "automation", "description": "Sends keys", "entities": [],
             "inputs": [], "outputs": [], "source_ref": ["modExp.Beep"], "support": "unsupported"}],
        "screens": [{"id": "SCR-001", "name": "AddExpense", "purpose": "Enter an expense", "inferred": True, "entities": ["Expense"],
                     "controls": [{"name": "Amount", "type": "number", "label": "Amount", "binds_to": "Expense.Amount"},
                                  {"name": "Category", "type": "text", "label": "Category", "binds_to": "Expense.Category"},
                                  {"name": "Save", "type": "button", "label": "Save", "binds_to": ""}],
                     "actions": [{"name": "Save", "description": "stores it", "calls": "AddExpense"},
                                 {"name": "Total", "description": "sum", "calls": "TotalFor"},
                                 {"name": "Nothing", "description": "", "calls": ""}],
                     "source_ref": ["modExp.AddExpense"], "support": "supported"}],
        "workflows": [{"id": "WFL-001", "name": "Import", "description": "load it", "trigger": "button click",
                       "steps": [{"order": 1, "description": "read", "rule": "AddExpense"}], "source_ref": ["modExp.Import"], "support": "supported"}],
        "reports": [
            {"id": "RPT-001", "name": "Summary", "format": "pdf", "description": "pdf summary", "data_from": ["Expense"], "source_ref": ["modExp.MakePdf"], "support": "unsupported"},
            {"id": "RPT-002", "name": "ExpenseCsv", "format": "csv", "description": "csv export", "data_from": ["Expense"], "source_ref": ["modExp.MakeCsv"], "support": "partial"}],
        "stubs": [{"procedure_id": "modExp.MakePdf", "module": "modExp", "name": "MakePdf", "start_line": 14, "end_line": 16, "level": "unsupported", "reason": "PDF via Excel"},
                  {"procedure_id": "modExp.Beep", "module": "modExp", "name": "Beep", "start_line": 20, "end_line": 22, "level": "unsupported", "reason": "SendKeys"},
                  {"procedure_id": "modExp.MakeCsv", "module": "modExp", "name": "MakeCsv", "start_line": 17, "end_line": 19, "level": "partial", "reason": "file write"}],
        "flags": [], "usage": {"tokens": 0, "calls": 0, "chunks": 0}}
    validate_artifact("migration_spec", s)
    return s


GOOD = {"RUL-001": "var e = new Expense { Amount = amount, Category = category };\nRepo<Expense>().Add(e);\nreturn true;",
        "RUL-002": "return Repo<Expense>().GetAll().Where(x => x.Category == category).Sum(x => x.Amount);",
        "WFL-001": 'return "imported";',
        "RPT-002": 'var csv = "a,b";\nreturn new ReportFile(System.Text.Encoding.UTF8.GetBytes(csv), "text/csv", "expenses.csv");'}


def reply(bodies):
    return {"methods": [{"id": k, "body": v} for k, v in bodies.items()]}


def gen(provider, spec_=None, **settings):
    s = fake_settings(**settings)
    gw = LlmGateway(provider, s, sleep=lambda _s: None)
    fs, manifest = generate_app(spec_ or spec(), VBA, ANALYSIS, gw, s)
    return fs, manifest, gw


class CSharpHelperTests(unittest.TestCase):
    def test_braces(self):
        self.assertTrue(braces_balanced('if (a) { var s = "}"; var c = \'{\'; // }\n }'))
        self.assertTrue(braces_balanced('var x = $"{a}"; var v = @"a ""} b"; { }'))
        self.assertFalse(braces_balanced("{ {"))
        self.assertFalse(braces_balanced("}"))

    def test_body_checks(self):
        self.assertIsNone(check_body('using (var w = new StringWriter()) { }\nreturn 1;'))
        for bad in ("using System.Text;\nreturn 1;", 'Process.Start("x");', "namespace X { }", "public class A { }",
                    "return System.Reflection.Assembly.GetExecutingAssembly();", 'File.Delete("a");', "", "if (x) {"):
            self.assertIsNotNone(check_body(bad), bad)

    def test_types_and_names(self):
        ents = {"expense": "Expense"}
        self.assertEqual([cs_type(t, ents) for t in ("Long", "Date", "List of Expense", "Expense[]", "", "Boolean", "Currency")],
                         ["int", "DateTime", "List<Expense>", "List<Expense>", "string", "bool", "decimal"])
        self.assertEqual(class_name("File"), "FileEntity")
        self.assertEqual(param_name("class", set()), "@class")
        self.assertEqual(param_name("Order Date", set()), "orderDate")
        self.assertEqual(cs_string('a"b\\c\n'), '"a\\"b\\\\c\\n"')
        self.assertEqual(razor_text('<b>@x"'), "&lt;b&gt;&#64;x&quot;")


class PlanTests(unittest.TestCase):
    def test_signatures_are_decided_by_the_platform(self):
        plan = build_plan(spec())
        self.assertEqual(plan.app, "ExpenseTracker")
        sigs = {m.id: m.signature for m in plan.methods}
        self.assertEqual(sigs["RUL-001"], "public bool AddExpense(decimal amount, string category)")
        self.assertEqual(sigs["RUL-002"], "public decimal TotalFor(string category)")
        self.assertEqual(sigs["RUL-003"], "public void PressKeys()")
        self.assertEqual(sigs["WFL-001"], "public string ImportWorkflow()")
        self.assertEqual(sigs["RPT-001"], "public ReportFile SummaryReport()")

    def test_stubs_are_decided_up_front(self):
        plan = build_plan(spec())
        stubs = {m.id: m.stub_reason for m in plan.methods if m.stub_reason}
        self.assertEqual(set(stubs), {"RUL-003", "RPT-001"})
        self.assertIn("SendKeys", stubs["RUL-003"])
        self.assertIn("QuestPDF", stubs["RPT-001"])

    def test_multiple_outputs_become_a_named_tuple(self):
        s = spec()
        s["rules"][0]["outputs"] = [{"name": "ok", "type": "bool"}, {"name": "message", "type": "string"}]
        self.assertIn("(bool Ok, string Message) AddExpense", build_plan(s).rules[0].signature)

    def test_entity_field_handling(self):
        s = spec()
        s["entities"][0]["fields"].append({"name": "Expense", "type": "string", "required": False, "notes": ""})
        s["entities"][0]["fields"][0] = {"name": "Id", "type": "string", "required": True, "notes": ""}
        names = [f.name for f in build_plan(s).entities[0].fields]
        self.assertIn("ExpenseValue", names)      # same name as the class
        self.assertIn("ExpenseCode", names)       # an Id that is not an int is renamed
        self.assertEqual(names.count("Id"), 0)

    def test_reserved_names_get_suffixes(self):
        s = spec()
        s["entities"][0]["name"] = "File"
        s["screens"][0]["name"] = "Index"
        plan = build_plan(s)
        self.assertEqual(plan.entities[0].cls, "FileEntity")
        self.assertEqual(plan.screens[0].cls, "IndexScreen")

    def test_app_name_never_equals_an_entity(self):
        s = spec()
        s["source_file"] = "Expense.xlsm"
        self.assertEqual(build_plan(s).app, "ExpenseApp")


class ScaffoldAndPageTests(unittest.TestCase):
    def test_scaffold_has_no_placeholders_and_targets_net8(self):
        files = scaffold_files("ExpenseTracker", "Expense Tracker", [("Home", "/Index")])
        for path, text in files.items():
            self.assertNotIn("__", text.replace("__init__", ""), path)
        self.assertIn("<TargetFramework>net8.0</TargetFramework>", files["ExpenseTracker/ExpenseTracker.csproj"])
        self.assertIn('"ExpenseTracker\\ExpenseTracker.csproj"', files["ExpenseTracker.sln"])

    def test_screen_page_wires_actions_to_rules(self):
        plan = build_plan(spec())
        files = screen_files(plan.app, plan)
        model = files["ExpenseTracker/Pages/AddExpense.cshtml.cs"]
        self.assertIn("public IActionResult OnPostSave()", model)
        # amount is decimal and the control is decimal: no conversion. category is a string control: direct.
        self.assertIn("_rules.AddExpense(Input.Amount, Input.Category)", model)
        self.assertIn("_rules.TotalFor(Input.Category)", model)
        self.assertIn("MIGRATION-TODO: the action Nothing has no migrated logic yet.", model)
        self.assertIn("catch (NotImplementedException ex)", model)
        view = files["ExpenseTracker/Pages/AddExpense.cshtml"]
        self.assertIn('asp-page-handler="Save"', view)
        self.assertIn('<input asp-for="Input.Amount" />', view)
        self.assertNotIn("Input.Save", view)        # buttons are not inputs

    def test_missing_control_gets_a_default_and_a_note(self):
        s = spec()
        s["screens"][0]["controls"] = [c for c in s["screens"][0]["controls"] if c["name"] != "Category"]
        plan = build_plan(s)
        model = screen_files(plan.app, plan)["ExpenseTracker/Pages/AddExpense.cshtml.cs"]
        self.assertIn("MIGRATION-TODO: no control supplies 'category'", model)
        self.assertIn("default(string)!", model)

    def test_type_mismatch_is_coerced(self):
        s = spec()
        s["screens"][0]["controls"][0]["type"] = "text"        # string control feeding a decimal input
        plan = build_plan(s)
        model = screen_files(plan.app, plan)["ExpenseTracker/Pages/AddExpense.cshtml.cs"]
        self.assertIn("Coerce.To<decimal>(Input.Amount)", model)

    def test_entity_input_is_built_from_matching_controls(self):
        s = spec()
        s["rules"][0]["inputs"] = [{"name": "expense", "type": "Expense"}]
        plan = build_plan(s)
        model = screen_files(plan.app, plan)["ExpenseTracker/Pages/AddExpense.cshtml.cs"]
        self.assertIn("new Expense { Amount = Input.Amount, Category = Input.Category }", model)

    def test_user_text_cannot_inject_razor(self):
        s = spec()
        s["screens"][0]["purpose"] = '@{ System.IO.File.Delete("x"); } <script>'
        plan = build_plan(s)
        view = screen_files(plan.app, plan)["ExpenseTracker/Pages/AddExpense.cshtml"]
        self.assertNotIn("@{ System", view)
        self.assertNotIn("<script>", view)


class GenerateTests(unittest.TestCase):
    def test_happy_path_and_one_call(self):
        fs, manifest, gw = gen(FakeProvider([reply(GOOD)]))
        validate_artifact("generation_manifest", manifest)
        self.assertEqual(gw.calls, 1)
        rules = fs.items["ExpenseTracker/Services/BusinessRules.Rules.cs"]["content"]
        self.assertIn("public bool AddExpense(decimal amount, string category)", rules)
        self.assertIn("Repo<Expense>().Add(e);", rules)
        self.assertIn("// RUL-001 AddExpense. Source: modExp.AddExpense", rules)
        self.assertTrue(braces_balanced(rules))

    def test_unsupported_rule_and_pdf_report_are_stubs_with_original_vba(self):
        fs, manifest, _ = gen(FakeProvider([reply(GOOD)]))
        rules = fs.items["ExpenseTracker/Services/BusinessRules.Rules.cs"]["content"]
        self.assertIn("public void PressKeys()", rules)
        self.assertIn("MIGRATION-TODO [UNSUPPORTED-RUL-003]", rules)
        self.assertIn('//       SendKeys "{ENTER}"', rules)
        self.assertIn('throw new NotImplementedException("MIGRATION-TODO [UNSUPPORTED-RUL-003]', rules)
        reports = fs.items["ExpenseTracker/Services/BusinessRules.Reports.cs"]["content"]
        self.assertIn("MIGRATION-TODO [UNSUPPORTED-RPT-001]", reports)
        self.assertIn("ExportAsFixedFormat", reports)
        self.assertIn("QuestPDF", reports)
        self.assertEqual({(s["spec_id"], s["cause"]) for s in manifest["stubs"]}, {("RUL-003", "unsupported"), ("RPT-001", "unsupported")})
        self.assertTrue(fs.items["ExpenseTracker/Services/BusinessRules.Reports.cs"]["is_stub"])

    def test_partial_methods_get_a_todo_comment(self):
        fs, _, _ = gen(FakeProvider([reply(GOOD)]))
        self.assertIn("MIGRATION-TODO [PARTIAL-RPT-002]", fs.items["ExpenseTracker/Services/BusinessRules.Reports.cs"]["content"])

    def test_prompt_contains_signatures_models_and_vba_but_not_stub_methods(self):
        provider = FakeProvider([reply(GOOD)])
        gen(provider)
        system, prompt = provider.calls[0]
        self.assertIn("public bool AddExpense(decimal amount, string category)", prompt)
        self.assertIn("class Expense : IEntity", prompt)
        self.assertIn("Cells(r, 1).Value = amt", prompt)
        self.assertIn("never use the network", system.lower())
        implement = prompt.split("Methods to implement:")[1]
        self.assertNotIn("PressKeys", implement)
        self.assertNotIn("SummaryReport", implement)

    def test_forbidden_code_is_rejected_then_stubbed_with_a_warning(self):
        bad = dict(GOOD)
        bad["RUL-002"] = 'System.Diagnostics.Process.Start("calc");\nreturn 0m;'
        fs, manifest, gw = gen(FakeProvider([reply(bad), reply(bad)]), schema_reask=1)
        self.assertEqual(gw.calls, 2)                     # the model was re-asked once
        rules = fs.items["ExpenseTracker/Services/BusinessRules.Rules.cs"]["content"]
        self.assertNotIn("Process.Start", rules)
        self.assertIn("Repo<Expense>().Add(e);", rules)    # the good method in the same batch survives
        self.assertIn("GENERATION_FAILED", [f["code"] for f in manifest["flags"]])
        self.assertEqual([u["id"] for u in manifest["uncovered_spec_items"]], ["RUL-002"])

    def test_reask_can_repair_a_bad_body(self):
        bad = dict(GOOD)
        bad["RUL-002"] = "return 1m;;; {"
        fs, manifest, _ = gen(FakeProvider([reply(bad), reply(GOOD)]), schema_reask=1)
        self.assertEqual(manifest["uncovered_spec_items"], [])
        self.assertIn(".Sum(x => x.Amount)", fs.items["ExpenseTracker/Services/BusinessRules.Rules.cs"]["content"])

    def test_non_void_body_without_return_is_rejected(self):
        bad = dict(GOOD)
        bad["WFL-001"] = "var x = 1;"
        _fs, manifest, _ = gen(FakeProvider([reply(bad)]), schema_reask=0)
        self.assertEqual([u["id"] for u in manifest["uncovered_spec_items"]], ["WFL-001"])

    def test_missing_method_in_reply_is_stubbed(self):
        partial = {k: v for k, v in GOOD.items() if k != "RPT-002"}
        _fs, manifest, _ = gen(FakeProvider([reply(partial)]), schema_reask=0)
        self.assertEqual([u["id"] for u in manifest["uncovered_spec_items"]], ["RPT-002"])

    def test_total_failure_stops_the_run(self):
        with self.assertRaises(BlockerError):
            gen(FakeProvider([{"methods": []}, {"methods": []}]), schema_reask=1)

    def test_bad_key_stops_the_run(self):
        with self.assertRaises(BlockerError):
            gen(FakeProvider([LlmPermanentError("Gemini rejected the API key (401).")]))

    def test_unreachable_model_stops_the_run(self):
        s = spec()
        provider = FakeProvider(responder=lambda p, n: LlmTransientError("503"))
        with self.assertRaises(BlockerError):
            gen(provider, s, llm_retries=0, chunk_max_chars=10)

    def test_batches_split_by_size(self):
        provider = FakeProvider(responder=lambda p, n: reply({k: v for k, v in GOOD.items() if f"id: {k}" in p.split("Methods to implement:")[1]}))
        _fs, manifest, gw = gen(provider, chunk_max_chars=40)
        self.assertGreater(gw.calls, 1)
        self.assertEqual(manifest["uncovered_spec_items"], [])

    def test_nothing_for_the_model_means_no_calls(self):
        s = spec()
        s["rules"] = [r for r in s["rules"] if r["id"] == "RUL-003"]
        s["workflows"] = []
        s["reports"] = [r for r in s["reports"] if r["id"] == "RPT-001"]
        provider = FakeProvider([])
        fs, manifest, _ = gen(provider, s)
        self.assertEqual(provider.calls, [])
        self.assertEqual(manifest["usage"]["calls"], 0)
        self.assertEqual(len(manifest["stubs"]), 2)

    def test_every_cs_file_has_balanced_braces_and_no_leftovers(self):
        fs, _, _ = gen(FakeProvider([reply(GOOD)]))
        for path, item in fs.items.items():
            text = item["content"]
            if path.endswith(".cs"):
                self.assertTrue(braces_balanced(text), path)
            self.assertNotIn("__APP__", text, path)
            self.assertNotIn("{{", text.replace("{{0:", ""), path)
        pages = [p for p in fs.items if p.endswith(".cshtml") and "_View" not in p and "_Layout" not in p]
        for p in pages:
            self.assertTrue(fs.items[p]["content"].startswith("@page"), p)

    def test_manifest_links_files_to_spec_items(self):
        _fs, manifest, _ = gen(FakeProvider([reply(GOOD)]))
        by_path = {f["path"]: f for f in manifest["files"]}
        self.assertEqual(by_path["ExpenseTracker/Models/Expense.cs"]["spec_refs"], ["ENT-001"])
        self.assertEqual(by_path["ExpenseTracker/Pages/AddExpense.cshtml"]["spec_refs"], ["SCR-001"])
        self.assertEqual(by_path["ExpenseTracker/Services/BusinessRules.Rules.cs"]["spec_refs"], ["RUL-001", "RUL-002", "RUL-003"])
        self.assertEqual(by_path["ExpenseTracker/Data/Expense.json"]["kind"], "data")
        self.assertIn("README.md", by_path)

    def test_readme_lists_stubs(self):
        fs, _, _ = gen(FakeProvider([reply(GOOD)]))
        text = fs.items["README.md"]["content"]
        self.assertIn("dotnet run", text)
        self.assertIn("RUL-003", text)


class WriteAndStageTests(unittest.TestCase):
    def test_write_app_refuses_paths_outside_the_folder(self):
        fs = FileSet()
        fs.add("../evil.txt", "x", "docs")
        with self.assertRaises(BlockerError):
            write_app(Path(tempfile.mkdtemp()) / "app", fs)

    def test_write_app_replaces_old_output(self):
        root = Path(tempfile.mkdtemp()) / "app"
        root.mkdir()
        (root / "old.txt").write_text("old")
        fs = FileSet()
        fs.add("a/b.txt", "new", "docs")
        write_app(root, fs)
        self.assertFalse((root / "old.txt").exists())
        self.assertEqual((root / "a" / "b.txt").read_text(), "new")

    def test_stage_writes_app_and_manifest(self):
        root = Path(tempfile.mkdtemp())
        ws = Workspace(root)
        store = RunStore(ws)
        rid = new_run_id()
        ws.create_run_dirs(rid)
        store.create(rid, "skill", "Expense Tracker.xlsm", ["generator"])
        ws.artifact_path(rid, "vba_modules").write_text(json.dumps(VBA))
        ws.artifact_path(rid, "analysis_model").write_text(json.dumps(ANALYSIS))
        ws.artifact_path(rid, "migration_spec").write_text(json.dumps(spec()))
        ctx = PluginContext(fake_settings(workspace_root=root), store, ws, llm_provider=FakeProvider([reply(GOOD)]))
        out = generator_stage({"run_id": rid}, ctx)
        app_dir = ws.output_dir(rid) / "app"
        self.assertTrue((app_dir / "ExpenseTracker.sln").is_file())
        self.assertTrue((app_dir / "ExpenseTracker" / "Program.cs").is_file())
        self.assertTrue((app_dir / "ExpenseTracker" / "Services" / "BusinessRules.Rules.cs").is_file())
        self.assertTrue(Path(out["manifest_path"]).is_file())
        self.assertTrue((ws.logs_dir(rid) / "llm" / "generator.jsonl").is_file())
        self.assertIsNone(store.read(rid)["detail"])

    def test_stage_without_spec_fails_clearly(self):
        root = Path(tempfile.mkdtemp())
        ws = Workspace(root)
        store = RunStore(ws)
        rid = new_run_id()
        ws.create_run_dirs(rid)
        store.create(rid, "skill", "t.xlsm", ["generator"])
        ctx = PluginContext(fake_settings(workspace_root=root), store, ws, llm_provider=FakeProvider([]))
        with self.assertRaises(BlockerError):
            generator_stage({"run_id": rid}, ctx)


if __name__ == "__main__":
    unittest.main()
