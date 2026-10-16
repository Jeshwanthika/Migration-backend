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
from app.plugins.xlsm_to_aspnetcore.analyzer import analyze_modules, analyzer_stage
from tests.fakes import FakeProvider, fake_settings

MOD = '''Attribute VB_Name = "Sales"
Option Explicit
Sub ImportData()
    Dim ws As Worksheet
    Set ws = Sheets("Data")
    Call Total
End Sub
Function Total() As Double
    Total = Application.WorksheetFunction.Sum(Range("B2:B10"))
End Function
Sub Beep()
    SendKeys "{ENTER}"
End Sub'''

VBA = {"source_file": "t.xlsm", "modules": [
    {"name": "Sales", "type": "standard", "stream": "s", "line_count": len(MOD.split("\n")), "code": MOD}], "findings": [], "flags": []}


def entry(name, **kw):
    base = {"name": name, "role": "utility", "summary": f"{name} does something.", "calls": [], "reads": [],
            "writes": [], "support": "supported", "support_reason": "plain VBA", "constructs": []}
    base.update(kw)
    return base


def full_reply(*names, **per):
    return {"module_summary": "Sales logic.", "procedures": [entry(n, **per.get(n, {})) for n in names]}


def run(provider, vba=VBA, **settings):
    s = fake_settings(**settings)
    gw = LlmGateway(provider, s, sleep=lambda _s: None)
    return analyze_modules(vba, gw, s), gw


class AnalyzeTests(unittest.TestCase):
    def test_happy_path_every_procedure_has_role_support_and_lines(self):
        reply = full_reply("ImportData", "Total", "Beep", ImportData={"role": "data_access", "calls": ["Total"], "reads": ["Data sheet"]},
                           Total={"role": "calculation", "reads": ["Sheet B2:B10"]})
        (model, flags), gw = run(FakeProvider([reply]))
        validate_artifact("analysis_model", model)
        procs = {p["name"]: p for p in model["procedures"]}
        self.assertEqual(set(procs), {"ImportData", "Total", "Beep"})
        self.assertEqual((procs["ImportData"]["start_line"], procs["ImportData"]["end_line"]), (3, 7))
        self.assertEqual((procs["Total"]["start_line"], procs["Total"]["end_line"]), (8, 10))
        self.assertEqual(procs["ImportData"]["role"], "data_access")
        self.assertEqual(procs["Total"]["returns"], "Double")
        self.assertTrue(all(p["analyzed"] for p in model["procedures"]))
        self.assertEqual(model["modules"][0]["summary"], "Sales logic.")
        self.assertEqual(model["usage"], {"tokens": 15, "calls": 1, "chunks": 1})

    def test_rule_scan_flags_sendkeys_even_if_model_says_supported(self):
        (model, flags), _ = run(FakeProvider([full_reply("ImportData", "Total", "Beep")]))
        beep = next(p for p in model["procedures"] if p["name"] == "Beep")
        self.assertEqual(beep["support"], "unsupported")
        sk = [f for f in flags if f["code"] == "UNSUPPORTED_SENDKEYS"]
        self.assertEqual(len(sk), 1)
        self.assertEqual(sk[0]["source_ref"], "Sales:12")
        self.assertEqual(sk[0]["severity"], "Warning")
        self.assertIn("SendKeys", sk[0]["snippet"])

    def test_llm_construct_becomes_flag_with_platform_line_number(self):
        reply = full_reply("ImportData", "Total", "Beep", Total={"support": "partial", "support_reason": "x", "constructs": [
            {"level": "partial", "construct": "WorksheetFunction", "snippet": "Total = Application.WorksheetFunction.Sum(Range(\"B2:B10\"))",
             "reason": "Needs a sum over entities", "suggested_action": "Use LINQ"}]})
        (model, flags), _ = run(FakeProvider([reply]))
        f = next(f for f in flags if f["code"] == "PARTIAL_CONSTRUCT")
        self.assertEqual(f["source_ref"], "Sales:9")
        self.assertEqual(f["support"], "partial")

    def test_llm_and_rule_flag_on_same_line_are_not_duplicated(self):
        reply = full_reply("ImportData", "Total", "Beep", Beep={"support": "unsupported", "support_reason": "x", "constructs": [
            {"level": "unsupported", "construct": "SendKeys", "snippet": 'SendKeys "{ENTER}"', "reason": "no keyboard"}]})
        (_model, flags), _ = run(FakeProvider([reply]))
        self.assertEqual(len([f for f in flags if f["source_ref"] == "Sales:12" and f["support"] == "unsupported"]), 1)

    def test_missing_procedure_gets_default_and_warning(self):
        (model, flags), _ = run(FakeProvider([full_reply("ImportData", "Total")]))
        beep = next(p for p in model["procedures"] if p["name"] == "Beep")
        self.assertFalse(beep["analyzed"])
        self.assertIn("PROCEDURE_NOT_ANALYZED", [f["code"] for f in flags])

    def test_unknown_entries_are_ignored_with_info_flag(self):
        (model, flags), _ = run(FakeProvider([full_reply("ImportData", "Total", "Beep", "Ghost")]))
        self.assertEqual(len(model["procedures"]), 3)
        self.assertIn("UNKNOWN_PROCEDURE_IGNORED", [f["code"] for f in flags])

    def test_invalid_reply_is_reasked_then_flagged_without_failing(self):
        provider = FakeProvider([{"nope": 1}, {"nope": 2}])
        (model, flags), gw = run(provider, schema_reask=1)
        self.assertEqual(len(provider.calls), 2)
        self.assertIn("CHUNK_ANALYSIS_FAILED", [f["code"] for f in flags])
        self.assertEqual(len(model["procedures"]), 3)
        self.assertTrue(not any(p["analyzed"] for p in model["procedures"]))
        # the rule scan still runs on the failed chunk
        self.assertIn("UNSUPPORTED_SENDKEYS", [f["code"] for f in flags])

    def test_reask_succeeds_on_second_try(self):
        provider = FakeProvider([{"bad": 1}, full_reply("ImportData", "Total", "Beep")])
        (model, flags), _ = run(provider, schema_reask=1)
        self.assertTrue(all(p["analyzed"] for p in model["procedures"]))
        self.assertNotIn("CHUNK_ANALYSIS_FAILED", [f["code"] for f in flags])

    def test_bad_key_fails_the_run(self):
        with self.assertRaises(BlockerError) as ctx:
            run(FakeProvider([LlmPermanentError("Gemini rejected the API key (401).")]))
        self.assertIn("API key", str(ctx.exception))

    def test_three_unreachable_chunks_in_a_row_fail_the_run(self):
        procs = "\n".join(f"Sub P{i}()\n x = {i}\nEnd Sub" for i in range(4))
        vba = {"source_file": "t", "modules": [{"name": "M", "type": "standard", "stream": "", "line_count": 12, "code": procs}],
               "findings": [], "flags": []}
        provider = FakeProvider(responder=lambda p, n: LlmTransientError("429"))
        with self.assertRaises(BlockerError):
            run(provider, vba=vba, chunk_max_chars=20, llm_retries=0)

    def test_one_unreachable_chunk_is_flagged_and_rest_continue(self):
        procs = "\n".join(f"Sub P{i}()\n x = {i}\nEnd Sub" for i in range(3))
        vba = {"source_file": "t", "modules": [{"name": "M", "type": "standard", "stream": "", "line_count": 9, "code": procs}],
               "findings": [], "flags": []}

        def responder(prompt, n):
            if n == 1:
                return LlmTransientError("429")
            body = prompt.split("Procedures to analyze:")[1]
            return full_reply(*[f"P{i}" for i in range(3) if f"Sub P{i}()" in body])
        (model, flags), _ = run(FakeProvider(responder=responder), vba=vba, chunk_max_chars=20, llm_retries=0)
        self.assertEqual([p["analyzed"] for p in model["procedures"]], [False, True, True])
        self.assertEqual([f["code"] for f in flags].count("CHUNK_ANALYSIS_FAILED"), 1)

    def test_large_module_is_chunked_at_procedure_boundaries(self):
        procs = "\n".join(f"Sub P{i}()\n x = {i}\nEnd Sub" for i in range(6))
        vba = {"source_file": "t", "modules": [{"name": "M", "type": "standard", "stream": "", "line_count": 18, "code": procs}],
               "findings": [], "flags": []}
        prompts = []

        def responder(prompt, n):
            prompts.append(prompt)
            names = [f"P{i}" for i in range(6) if f"Sub P{i}()\n x = {i}\nEnd Sub" in prompt.split("Procedures to analyze:")[1]]
            return full_reply(*names)
        (model, _flags), gw = run(FakeProvider(responder=responder), vba=vba, chunk_max_chars=40)
        self.assertGreater(gw.calls, 1)
        self.assertEqual(sorted(p["name"] for p in model["procedures"]), [f"P{i}" for i in range(6)])
        self.assertTrue(all(p["analyzed"] for p in model["procedures"]))
        # every chunk holds whole procedures only
        for prompt in prompts:
            body = prompt.split("Procedures to analyze:")[1]
            self.assertEqual(body.count("' ---- Sub"), body.count("End Sub"))

    def test_module_without_procedures_needs_no_call(self):
        vba = {"source_file": "t", "modules": [{"name": "Decls", "type": "standard", "stream": "", "line_count": 2,
                                                  "code": "Option Explicit\nPublic X As Long"}], "findings": [], "flags": []}
        provider = FakeProvider([])
        (model, _flags), _ = run(provider, vba=vba)
        self.assertEqual(provider.calls, [])
        self.assertEqual(model["procedures"], [])
        self.assertIn("no procedures", model["modules"][0]["summary"])

    def test_prompt_tells_model_not_to_invent_sheet_contents(self):
        provider = FakeProvider([full_reply("ImportData", "Total", "Beep")])
        run(provider)
        system, prompt = provider.calls[0]
        self.assertIn("Never invent", system)
        self.assertIn("Sub ImportData", prompt)
        self.assertNotIn("Attribute VB_Name", prompt)


class NoiseTests(unittest.TestCase):
    CODE = '''Sub Run()
    Application.EnableEvents = False
    Range("A" & r).Value = 1
    Range("B" & r).Value = 2
    Application.EnableEvents = True
    ActiveSheet.Select
End Sub'''

    def vba(self):
        return {"source_file": "t", "modules": [{"name": "M", "type": "standard", "stream": "", "line_count": 7, "code": self.CODE}],
                "findings": [], "flags": []}

    def test_excel_only_constructs_are_info_grouped_and_do_not_change_support(self):
        reply = full_reply("Run", Run={"constructs": [
            {"level": "ignorable", "construct": "ScreenUpdating", "snippet": "Application.EnableEvents = False", "reason": "no-op"}]})
        (model, flags), _ = run(FakeProvider([reply]), vba=self.vba())
        self.assertEqual(model["procedures"][0]["support"], "supported")
        self.assertTrue(all(f["severity"] == "Info" for f in flags), flags)
        codes = [f["code"] for f in flags]
        self.assertEqual(codes.count("IGNORABLE_EXCEL_UI_ONLY"), 1)   # grouped, not one per line
        self.assertEqual(codes.count("IGNORABLE_DYNAMIC_RANGE"), 1)
        grouped = next(f for f in flags if f["code"] == "IGNORABLE_EXCEL_UI_ONLY")
        self.assertIn("3 places", grouped["reason"])

    def test_llm_ignorable_construct_never_raises_warning(self):
        vba = {"source_file": "t", "modules": [{"name": "M", "type": "standard", "stream": "", "line_count": 3,
               "code": "Sub A()\n    Debug.Print 1\nEnd Sub"}], "findings": [], "flags": []}
        reply = full_reply("A", A={"constructs": [{"level": "ignorable", "construct": "Debug", "snippet": "Debug.Print 1", "reason": "dropped"}]})
        (model, flags), _ = run(FakeProvider([reply]), vba=vba)
        self.assertEqual([f["severity"] for f in flags], ["Info"])
        self.assertEqual(model["procedures"][0]["support"], "supported")


class DuplicateTests(unittest.TestCase):
    CODE = '''Sub Pdf()
    x = 1
    ws.ExportAsFixedFormat Type:=xlTypePDF, _
        Filename:=p
End Sub
Sub Csv()
    Open p For Output As #1
    Print #1, ln
    Close #1
End Sub'''

    def test_multiline_statement_and_file_writes_give_one_flag_each(self):
        vba = {"source_file": "t", "modules": [{"name": "M", "type": "standard", "stream": "", "line_count": 10, "code": self.CODE}],
               "findings": [], "flags": []}
        reply = full_reply("Pdf", "Csv",
            Pdf={"support": "unsupported", "support_reason": "x", "constructs": [{"level": "unsupported", "construct": "ExportAsFixedFormat",
                 "snippet": "ws.ExportAsFixedFormat Type:=xlTypePDF, Filename:=p", "reason": "needs Excel"}]},
            Csv={"support": "partial", "support_reason": "x", "constructs": [{"level": "partial", "construct": "Print #",
                 "snippet": "Print #1, ln", "reason": "legacy file write"}]})
        (_model, flags), _ = run(FakeProvider([reply]), vba=vba)
        warn = [f for f in flags if f["severity"] == "Warning"]
        self.assertEqual(sorted(f["source_ref"] for f in warn), ["M:3", "M:7"])
        self.assertEqual(len(warn), 2)


class StageTests(unittest.TestCase):
    def make(self, provider):
        root = Path(tempfile.mkdtemp())
        ws = Workspace(root)
        store = RunStore(ws)
        run_id = new_run_id()
        ws.create_run_dirs(run_id)
        store.create(run_id, "skill", "t.xlsm", ["intake_check", "extractor", "analyzer"])
        ctx = PluginContext(fake_settings(workspace_root=root), store, ws, llm_provider=provider)
        return ws, store, ctx, run_id

    def test_stage_writes_artifact_and_logs_llm_calls(self):
        ws, store, ctx, rid = self.make(FakeProvider([full_reply("ImportData", "Total", "Beep")]))
        (ws.artifact_path(rid, "vba_modules")).write_text(json.dumps(VBA))
        out = analyzer_stage({"run_id": rid}, ctx)
        self.assertTrue(Path(out["analysis_path"]).is_file())
        self.assertEqual(out["tokens_used"], 15)
        self.assertTrue((ws.logs_dir(rid) / "llm" / "analyzer.jsonl").is_file())
        self.assertIsNone(store.read(rid)["detail"])

    def test_stage_without_extraction_fails_clearly(self):
        ws, store, ctx, rid = self.make(FakeProvider([]))
        with self.assertRaises(BlockerError):
            analyzer_stage({"run_id": rid}, ctx)

    def test_missing_key_gives_clear_message(self):
        ws, store, ctx, rid = self.make(None)
        ws.artifact_path(rid, "vba_modules").write_text(json.dumps(VBA))
        with self.assertRaises(BlockerError) as e:
            analyzer_stage({"run_id": rid}, ctx)
        self.assertIn("GEMINI_API_KEY", str(e.exception))


if __name__ == "__main__":
    unittest.main()
