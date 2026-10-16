import json
import tempfile
import unittest
from pathlib import Path

from app.core.context import PluginContext
from app.core.errors import BlockerError
from app.core.llm import LlmGateway, LlmPermanentError, LlmTransientError
from app.core.run_store import RunStore
from app.core.schema_validation import validate_artifact
from app.core.workspace import Workspace, new_run_id
from app.plugins.xlsm_to_aspnetcore.spec_architect import build_spec, spec_architect_stage
from app.plugins.xlsm_to_aspnetcore.spec_merge import (
    apply_entity_merges, finish_spec, merge_chunks, norm_field_type, norm_key, pascal,
)
from app.plugins.xlsm_to_aspnetcore.spec_render import render_spec_markdown
from tests.fakes import FakeProvider, fake_settings
from tests.test_analyzer import VBA, full_reply
from tests.test_analyzer import run as run_analyzer


def analysis_fixture():
    reply = full_reply("ImportData", "Total", "Beep", ImportData={"role": "data_access", "reads": ["Data sheet"]},
                       Total={"role": "calculation"})
    (model, _flags), _ = run_analyzer(FakeProvider([reply]))
    return model


def chunk(**kw):
    base = {"entities": [], "rules": [], "screens": [], "workflows": [], "reports": [], "open_questions": []}
    base.update(kw)
    return base


def entity(name, fields=(("Amount", "Currency"),), refs=("Sales.Total",), **kw):
    e = {"name": name, "description": f"{name} record", "inferred": True,
         "fields": [{"name": n, "type": t, "required": True, "notes": ""} for n, t in fields], "source_ref": list(refs)}
    e.update(kw)
    return e


def rule(name, refs=("Sales.Total",), **kw):
    r = {"name": name, "kind": "calculation", "description": f"{name} logic", "source_ref": list(refs)}
    r.update(kw)
    return r


def good_chunk():
    return chunk(
        entities=[entity("Expenses", (("amount", "Currency"), ("Date", "Date")))],
        rules=[rule("calculate total", entities=["Expense"])],
        screens=[{"name": "Add Expense", "purpose": "Enter an expense", "inferred": True, "entities": ["Expense"],
                  "controls": [{"name": "amount", "type": "TextBox", "label": "Amount", "binds_to": "Expense.Amount"}],
                  "actions": [{"name": "Save", "description": "stores it", "calls": "CalculateTotal"}],
                  "source_ref": ["Sales.ImportData"]}],
        workflows=[{"name": "Import", "description": "load data", "trigger": "button click",
                    "steps": ["read the sheet", {"description": "add up", "rule": "calculate total"}], "source_ref": ["Sales.ImportData"]}],
        reports=[{"name": "Summary", "format": "Excel", "description": "totals", "data_from": ["expenses"], "source_ref": ["Sales.Total"]}],
    )


def make_build(provider, **settings):
    s = fake_settings(**settings)
    gw = LlmGateway(provider, s, sleep=lambda _s: None)
    return build_spec(VBA, analysis_fixture(), gw, s), gw


class HelperTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(pascal("add new expense"), "AddNewExpense")
        self.assertEqual(pascal("ExpenseItem"), "ExpenseItem")
        self.assertEqual(pascal("9lives"), "N9lives")
        self.assertEqual(pascal("", "X"), "X")
        self.assertEqual(norm_key("Expenses"), norm_key("expense"))
        self.assertNotEqual(norm_key("Address"), norm_key("Addres"))

    def test_type_normalization(self):
        self.assertEqual([norm_field_type(t) for t in ("Currency", "Long", "Boolean", "Date", "Whatever")],
                         ["decimal", "int", "bool", "date", "string"])


class MergeTests(unittest.TestCase):
    def test_same_entity_in_two_chunks_is_merged_with_all_fields_and_refs(self):
        a = chunk(entities=[entity("Expense", (("Amount", "double"),), refs=("A.x",))])
        b = chunk(entities=[entity("expenses", (("amount", "decimal"), ("Category", "string")), refs=("B.y",))])
        parts = merge_chunks([a, b])
        self.assertEqual(len(parts["entities"]), 1)
        e = parts["entities"][0]
        self.assertEqual([f["name"] for f in e["fields"]], ["Amount", "Category"])
        self.assertEqual(e["source_ref"], ["A.x", "B.y"])
        self.assertEqual(e["fields"][0]["type"], "decimal")

    def test_entity_is_explicit_if_any_mention_is_explicit(self):
        parts = merge_chunks([chunk(entities=[entity("Item", inferred=False)]), chunk(entities=[entity("Item", inferred=True)])])
        self.assertFalse(parts["entities"][0]["inferred"])      # a VBA Type seen once makes it explicit
        parts = merge_chunks([chunk(entities=[entity("Item")]), chunk(entities=[entity("Item")])])
        self.assertTrue(parts["entities"][0]["inferred"])

    def test_workflow_keeps_longest_step_list_and_string_steps(self):
        parts = merge_chunks([chunk(workflows=[{"name": "W", "description": "", "steps": ["a"], "source_ref": []}]),
                              chunk(workflows=[{"name": "W", "description": "", "steps": ["a", {"description": "b", "rule": "do it"}], "source_ref": []}])])
        steps = parts["workflows"][0]["steps"]
        self.assertEqual([(s["order"], s["description"], s["rule"]) for s in steps], [(1, "a", ""), (2, "b", "DoIt")])

    def test_entity_alias_merge_rewrites_references(self):
        parts = merge_chunks([chunk(entities=[entity("Expense", (("Amount", "decimal"),)), entity("ExpenseRow", (("Note", "string"),))],
                                    rules=[rule("R", entities=["ExpenseRow"])], reports=[{"name": "Rp", "format": "csv", "description": "", "data_from": ["ExpenseRow"], "source_ref": []}])])
        applied = apply_entity_merges(parts, [{"canonical": "Expense", "aliases": ["ExpenseRow", "Ghost"]}])
        self.assertEqual(applied, 1)
        self.assertEqual([e["name"] for e in parts["entities"]], ["Expense"])
        self.assertEqual([f["name"] for f in parts["entities"][0]["fields"]], ["Amount", "Note"])
        self.assertEqual(parts["rules"][0]["entities"], ["Expense"])
        self.assertEqual(parts["reports"][0]["data_from"], ["Expense"])


class FinishTests(unittest.TestCase):
    def finish(self, parts_chunk):
        flags = []
        spec = finish_spec(merge_chunks([parts_chunk]), analysis_fixture(), "t.xlsm", {"tokens": 0, "calls": 0, "chunks": 0}, flags)
        validate_artifact("migration_spec", spec)
        return spec, flags

    def test_ids_support_and_unknown_refs(self):
        spec, flags = self.finish(chunk(
            entities=[entity("Expense", refs=("Sales.Total", "Sales.Nope"))],
            rules=[rule("Beeper", refs=("Sales.Beep",)), rule("Orphan", refs=("Sales.Nope",))]))
        self.assertEqual(spec["entities"][0]["id"], "ENT-001")
        self.assertEqual(spec["entities"][0]["source_ref"], ["Sales.Total"])
        by_name = {r["name"]: r for r in spec["rules"]}
        self.assertEqual(by_name["Beeper"]["support"], "unsupported")        # SendKeys in Beep
        self.assertEqual(by_name["Orphan"]["support"], "partial")
        codes = [f["code"] for f in flags]
        self.assertIn("SPEC_UNKNOWN_REFERENCE", codes)
        self.assertIn("SPEC_ELEMENT_UNTRACED", codes)

    def test_stubs_come_from_analysis_not_the_model(self):
        spec, _ = self.finish(chunk())
        self.assertEqual([(s["name"], s["level"]) for s in spec["stubs"]], [("Beep", "unsupported")])
        self.assertEqual((spec["stubs"][0]["start_line"], spec["stubs"][0]["end_line"]), (11, 13))

    def test_open_questions_become_warning_flags(self):
        spec, flags = self.finish(chunk(open_questions=[{"text": "What is cell Z1 for?", "source_ref": ["Sales.ImportData"]}]))
        f = next(f for f in flags if f["code"] == "SPEC_OPEN_QUESTION")
        self.assertEqual((f["severity"], f["source_ref"]), ("Warning", "Sales.ImportData"))

    def test_unknown_entity_names_are_dropped_from_links(self):
        spec, _ = self.finish(chunk(entities=[entity("Expense")], rules=[rule("R", entities=["Expense", "Phantom"])]))
        self.assertEqual(spec["rules"][0]["entities"], ["Expense"])


class BuildTests(unittest.TestCase):
    def test_happy_path_validates_and_uses_reconcile(self):
        extra = chunk(entities=[entity("Expense"), entity("ExpenseRow", (("Note", "string"),))])
        provider = FakeProvider([extra, {"merge": [{"canonical": "Expense", "aliases": ["ExpenseRow"]}]}])
        spec, gw = make_build(provider)
        validate_artifact("migration_spec", spec)
        self.assertEqual([e["name"] for e in spec["entities"]], ["Expense"])
        self.assertEqual(gw.calls, 2)
        self.assertIn("SPEC_ENTITIES_MERGED", [f["code"] for f in spec["flags"]])
        self.assertEqual(spec["usage"], {"tokens": 30, "calls": 2, "chunks": 1})

    def test_full_chunk_produces_every_element_kind(self):
        spec, _ = make_build(FakeProvider([good_chunk()]))
        self.assertEqual([len(spec[k]) for k in ("entities", "rules", "screens", "workflows", "reports")], [1, 1, 1, 1, 1])
        self.assertEqual(spec["entities"][0]["name"], "Expenses")
        self.assertEqual(spec["rules"][0]["name"], "CalculateTotal")
        self.assertEqual(spec["screens"][0]["actions"][0]["calls"], "CalculateTotal")
        self.assertEqual(spec["workflows"][0]["steps"][1]["rule"], "CalculateTotal")
        self.assertEqual(spec["reports"][0]["format"], "xlsx")
        self.assertEqual(spec["reports"][0]["data_from"], ["Expenses"])
        self.assertEqual(spec["screens"][0]["controls"][0]["type"], "text")

    def test_prompt_has_ids_analysis_and_no_invention_rule(self):
        provider = FakeProvider([good_chunk()])
        make_build(provider)
        system, prompt = provider.calls[0]
        self.assertIn("never invent", system.lower())
        self.assertIn("[Sales.ImportData]", prompt)
        self.assertIn('"role": "data_access"', prompt)
        self.assertNotIn("Attribute VB_Name", prompt)

    def test_later_chunks_see_what_was_already_found(self):
        procs = "\n".join(f"Sub P{i}()\n x = {i}\nEnd Sub" for i in range(3))
        vba = {"source_file": "t", "modules": [{"name": "M", "type": "standard", "stream": "", "line_count": 9, "code": procs}], "findings": [], "flags": []}
        s = fake_settings(chunk_max_chars=20)
        from app.plugins.xlsm_to_aspnetcore.analyzer import analyze_modules
        names = ["P0", "P1", "P2"]
        analysis, _ = analyze_modules(vba, LlmGateway(FakeProvider(responder=lambda p, n: full_reply(*[x for x in names if f"Sub {x}()" in p.split("Procedures to analyze:")[1]])), s, sleep=lambda _s: None), s)
        provider = FakeProvider(responder=lambda p, n: chunk(entities=[entity("Thing", (("Name", "string"),), refs=("M.P0",))]) if n == 1 else chunk())
        spec = build_spec(vba, analysis, LlmGateway(provider, s, sleep=lambda _s: None), s)
        self.assertEqual(len(provider.calls), 3)
        self.assertNotIn("Already found", provider.calls[0][1])
        self.assertIn("Entity Thing: Name", provider.calls[1][1])
        self.assertEqual(len(spec["entities"]), 1)

    def test_failed_chunk_is_flagged_and_other_chunks_still_count(self):
        procs = "\n".join(f"Sub P{i}()\n x = {i}\nEnd Sub" for i in range(2))
        vba = {"source_file": "t", "modules": [{"name": "M", "type": "standard", "stream": "", "line_count": 6, "code": procs}], "findings": [], "flags": []}
        s = fake_settings(chunk_max_chars=20, llm_retries=0, schema_reask=0)
        from app.plugins.xlsm_to_aspnetcore.analyzer import analyze_modules
        analysis, _ = analyze_modules(vba, LlmGateway(FakeProvider(responder=lambda p, n: full_reply(*[x for x in ("P0", "P1") if f"Sub {x}()" in p.split("Procedures to analyze:")[1]])), s, sleep=lambda _s: None), s)
        provider = FakeProvider(responder=lambda p, n: {"bad": 1} if n == 1 else chunk(rules=[rule("Ok", refs=("M.P1",))]))
        spec = build_spec(vba, analysis, LlmGateway(provider, s, sleep=lambda _s: None), s)
        self.assertEqual([r["name"] for r in spec["rules"]], ["Ok"])
        self.assertIn("SPEC_CHUNK_FAILED", [f["code"] for f in spec["flags"]])

    def test_every_chunk_failing_stops_the_run(self):
        with self.assertRaises(BlockerError):
            make_build(FakeProvider([{"bad": 1}, {"bad": 2}]), schema_reask=1)

    def test_bad_key_stops_the_run(self):
        with self.assertRaises(BlockerError):
            make_build(FakeProvider([LlmPermanentError("Gemini rejected the API key (401).")]))

    def test_reconcile_failure_is_not_fatal(self):
        provider = FakeProvider([chunk(entities=[entity("A"), entity("B")]), LlmTransientError("503")] + [LlmTransientError("503")] * 5)
        spec, _ = make_build(provider, llm_retries=0)
        self.assertEqual(len(spec["entities"]), 2)
        self.assertIn("SPEC_RECONCILE_SKIPPED", [f["code"] for f in spec["flags"]])

    def test_no_procedures_gives_empty_spec_without_calls(self):
        empty = {"schema_version": "1.0", "source_file": "t", "modules": [], "procedures": [], "flags": [], "usage": {"tokens": 0, "calls": 0, "chunks": 0}}
        provider = FakeProvider([])
        s = fake_settings()
        spec = build_spec({"source_file": "t", "modules": []}, empty, LlmGateway(provider, s), s)
        validate_artifact("migration_spec", spec)
        self.assertEqual(provider.calls, [])
        self.assertEqual(spec["flags"][0]["code"], "SPEC_NOTHING_TO_SPECIFY")


class RenderAndStageTests(unittest.TestCase):
    def test_markdown_has_sections_ids_and_sources(self):
        spec, _ = make_build(FakeProvider([good_chunk()]))
        md = render_spec_markdown(spec)
        for heading in ("## Entities", "## Business rules", "## Screens", "## Workflows", "## Reports and exports",
                        "## Procedures that need attention", "## Flags"):
            self.assertIn(heading, md)
        self.assertIn("ENT-001 Expenses", md)
        self.assertIn("`Sales.Total`", md)
        self.assertIn("| Amount | decimal |", md)

    def test_stage_writes_json_and_markdown(self):
        root = Path(tempfile.mkdtemp())
        ws = Workspace(root)
        store = RunStore(ws)
        rid = new_run_id()
        ws.create_run_dirs(rid)
        store.create(rid, "skill", "t.xlsm", ["spec_architect"])
        ws.artifact_path(rid, "vba_modules").write_text(json.dumps(VBA))
        ws.artifact_path(rid, "analysis_model").write_text(json.dumps(analysis_fixture()))
        ctx = PluginContext(fake_settings(workspace_root=root), store, ws, llm_provider=FakeProvider([good_chunk()]))
        out = spec_architect_stage({"run_id": rid}, ctx)
        self.assertTrue(Path(out["spec_path"]).is_file())
        self.assertTrue(Path(out["spec_markdown_path"]).read_text().startswith("# Migration specification"))
        self.assertTrue((ws.logs_dir(rid) / "llm" / "spec_architect.jsonl").is_file())
        self.assertIsNone(store.read(rid)["detail"])

    def test_stage_without_analysis_fails_clearly(self):
        root = Path(tempfile.mkdtemp())
        ws = Workspace(root)
        store = RunStore(ws)
        rid = new_run_id()
        ws.create_run_dirs(rid)
        store.create(rid, "skill", "t.xlsm", ["spec_architect"])
        ctx = PluginContext(fake_settings(workspace_root=root), store, ws, llm_provider=FakeProvider([]))
        with self.assertRaises(BlockerError):
            spec_architect_stage({"run_id": rid}, ctx)


if __name__ == "__main__":
    unittest.main()
