import unittest

from app.plugins.xlsm_to_aspnetcore.chunker import make_chunks
from app.plugins.xlsm_to_aspnetcore.procedures import parse_header, procedure_id, split_module
from app.plugins.xlsm_to_aspnetcore.scanner import scan_declarations, scan_procedure

CODE = '''Attribute VB_Name = "Mod1"
Option Explicit
Public Const TAX As Double = 0.1
' Sub Fake()
Public Function Calc(ByVal a As Long, Optional b As Double = 2, ParamArray rest() As Variant) As Double
    Calc = a * b ' End Function
End Function

Private Sub Foo(x() As String, _
        y As Integer)
    MsgBox "End Sub"
End Sub
Property Get Bar() As String
End Property
Property Let Bar(v As String)
End Property
Sub Unfinished()
  x = 1'''


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.decl, self.procs = split_module(CODE)

    def test_finds_all_procedures_with_line_ranges(self):
        got = [(p.kind, p.name, p.start_line, p.end_line) for p in self.procs]
        self.assertEqual(got, [("Function", "Calc", 5, 7), ("Sub", "Foo", 9, 12), ("Property Get", "Bar", 13, 14),
                               ("Property Let", "Bar", 15, 16), ("Sub", "Unfinished", 17, 18)])

    def test_line_ranges_match_source_text(self):
        lines = CODE.split("\n")
        for p in self.procs:
            self.assertEqual(p.text, "\n".join(lines[p.start_line - 1:p.end_line]))

    def test_declarations_exclude_attributes_and_comments(self):
        self.assertEqual(self.decl, "Option Explicit\nPublic Const TAX As Double = 0.1")

    def test_params_and_return(self):
        calc = self.procs[0]
        self.assertEqual([p["name"] for p in calc.params], ["a", "b", "rest"])
        self.assertTrue(calc.params[0]["by_val"])
        self.assertTrue(calc.params[1]["optional"])
        self.assertEqual(calc.params[2]["type"], "Variant()")
        self.assertEqual(calc.returns, "Double")
        self.assertEqual(self.procs[1].params[0]["type"], "String()")

    def test_unterminated_procedure_is_marked(self):
        self.assertFalse(self.procs[-1].terminated)
        self.assertTrue(self.procs[0].terminated)

    def test_end_inside_string_or_comment_does_not_close(self):
        self.assertEqual(self.procs[1].end_line, 12)
        self.assertEqual(self.procs[0].end_line, 7)

    def test_declare_statement_is_not_a_procedure(self):
        _d, procs = split_module('Private Declare PtrSafe Function GetTickCount Lib "kernel32" () As Long\nSub A()\nEnd Sub')
        self.assertEqual([p.name for p in procs], ["A"])

    def test_header_parse_none_for_other_lines(self):
        self.assertIsNone(parse_header("Dim x As Long"))

    def test_ids_are_unique(self):
        taken = set()
        ids = [procedure_id("M", p, taken) for p in self.procs]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual(ids[2], "M.Bar")
        self.assertEqual(ids[3], "M.Bar.Let")

    def test_empty_code(self):
        self.assertEqual(split_module(""), ("", []))


class ChunkTests(unittest.TestCase):
    def procs(self, sizes):
        code = "\n".join(f"Sub P{i}()\n" + "x = 1\n" * 0 + ("'" + "a" * n + "\n") + "End Sub" for i, n in enumerate(sizes))
        return split_module(code)[1]

    def test_groups_without_cutting(self):
        procs = self.procs([50, 50, 50, 50])
        chunks = make_chunks(procs, max_chars=200)
        self.assertEqual(sum(len(c) for c in chunks), 4)
        self.assertTrue(all(sum(len(p.text) for p in c) <= 200 or len(c) == 1 for c in chunks))
        self.assertGreater(len(chunks), 1)

    def test_oversized_procedure_gets_own_chunk(self):
        procs = self.procs([10, 500, 10])
        chunks = make_chunks(procs, max_chars=100)
        self.assertEqual([[p.name for p in c] for c in chunks], [["P0"], ["P1"], ["P2"]])

    def test_everything_fits_one_chunk(self):
        self.assertEqual(len(make_chunks(self.procs([10, 10]), 10000)), 1)


class ScannerTests(unittest.TestCase):
    def codes(self, body):
        _d, procs = split_module("Sub T()\n" + body + "\nEnd Sub")
        return {(f["level"], f["code"]) for f in scan_procedure(procs[0])}

    def test_unsupported(self):
        cases = {
            'Set o = CreateObject("Outlook.Application")': "COM_AUTOMATION",
            'SendKeys "{ENTER}"': "SENDKEYS",
            'Application.OnTime Now + 1, "X"': "ONTIME_SCHEDULER",
            'Shell "calc.exe"': "SHELL_CALL",
            'Set c = ActiveSheet.ChartObjects.Add(1, 1, 1, 1)': "CHARTS",
            'ActiveSheet.PivotTables(1).RefreshTable': "PIVOT_TABLES",
            'Set cn = CreateObject("ADODB.Connection")': "DATABASE_ACCESS",
        }
        for body, code in cases.items():
            self.assertIn(("unsupported", code), self.codes(body), body)

    def test_partial(self):
        cases = {
            'Open "a.txt" For Output As #1': "FILE_WRITE",
            'Print #1, ln': "FILE_WRITE",
            'Application.Calculation = xlManual': "APPLICATION_STATE",
            'If Cells(1, 1).Interior.Color = vbRed Then x = 1': "FORMAT_DEPENDENT",
        }
        for body, code in cases.items():
            self.assertIn(("partial", code), self.codes(body), body)

    def test_excel_only_settings_are_ignorable(self):
        cases = ['Application.ScreenUpdating = False', 'Application.EnableEvents = True', 'ActiveWindow.DisplayGridlines = False',
                 'ws.Activate', 'ws.Range("A1").Select', 'With ws.PageSetup', 'p = Application.DefaultFilePath',
                 'Range("A" & r).Value = 1']
        for body in cases:
            levels = {lvl for lvl, _c in self.codes(body)}
            self.assertEqual(levels, {"ignorable"}, body)

    def test_pdf_export_is_unsupported(self):
        self.assertIn(("unsupported", "EXPORT_PDF"), self.codes('ws.ExportAsFixedFormat Type:=xlTypePDF'))

    def test_supported_code_has_no_findings(self):
        self.assertEqual(self.codes('Set d = CreateObject("Scripting.Dictionary")\nx = Range("A1").Value\nMsgBox x'), set())

    def test_comments_are_ignored(self):
        self.assertEqual(self.codes("' SendKeys is not used here"), set())

    def test_worksheet_change_event_is_partial(self):
        _d, procs = split_module("Private Sub Worksheet_Change(ByVal Target As Range)\nEnd Sub")
        self.assertEqual([f["code"] for f in scan_procedure(procs[0])], ["WORKSHEET_CHANGE_EVENT"])

    def test_line_numbers(self):
        _d, procs = split_module("Sub T()\nx = 1\nSendKeys \"a\"\nEnd Sub")
        self.assertEqual(scan_procedure(procs[0])[0]["line"], 3)

    def test_declare_outside_procedure(self):
        code = 'Private Declare PtrSafe Function GetTickCount Lib "kernel32" () As Long\nSub A()\nEnd Sub'
        _d, procs = split_module(code)
        found = scan_declarations(code, procs)
        self.assertEqual([(f["code"], f["line"]) for f in found], [("WIN32_DECLARE", 1)])


if __name__ == "__main__":
    unittest.main()
