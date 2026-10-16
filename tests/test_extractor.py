import unittest

from app.core.errors import BlockerError
from app.core.schema_validation import validate_artifact
from app.plugins.xlsm_to_aspnetcore.extractor import build_artifact
from app.plugins.xlsm_to_aspnetcore.module_types import classify_module, meaningful_line_count

STD = 'Attribute VB_Name = "Module1"\nOption Explicit\nSub Hello()\n  MsgBox "hi"\nEnd Sub\n'
SHEET = ('Attribute VB_Name = "Sheet1"\nAttribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"\n'
         'Private Sub Worksheet_Change(ByVal Target As Range)\nEnd Sub\n')
WBOOK = ('Attribute VB_Name = "ThisWorkbook"\nAttribute VB_Base = "0{00020819-0000-0000-C000-000000000046}"\n'
         'Private Sub Workbook_Open()\nEnd Sub\n')
CLASS = ('Attribute VB_Name = "Calc"\nAttribute VB_Base = "0{FCFB3D2A-A0FA-1068-A738-08002B3371B5}"\n'
         'Public Function Add(a, b)\n Add = a + b\nEnd Function\n')
FORM = ('Attribute VB_Name = "frmMain"\nAttribute VB_Base = "0{AB1B0C32-1111-2222-3333-444455556666}{AB1B0C32-1111-2222-3333-444455556667}"\n'
        'Private Sub CommandButton1_Click()\nEnd Sub\n')
EMPTY_SHEET = 'Attribute VB_Name = "Sheet2"\nAttribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"\n'


class ClassifyTests(unittest.TestCase):
    def test_types(self):
        self.assertEqual(classify_module("Module1", STD, "Module1.bas"), "standard")
        self.assertEqual(classify_module("Sheet1", SHEET), "sheet")
        self.assertEqual(classify_module("ThisWorkbook", WBOOK), "workbook")
        self.assertEqual(classify_module("Calc", CLASS), "class")
        self.assertEqual(classify_module("frmMain", FORM), "form")

    def test_workbook_by_name_without_attributes(self):
        self.assertEqual(classify_module("ThisWorkbook", "Sub x()\nEnd Sub"), "workbook")

    def test_line_count_ignores_attributes_and_options(self):
        self.assertEqual(meaningful_line_count(EMPTY_SHEET), 0)
        self.assertEqual(meaningful_line_count("Option Explicit\n\n"), 0)
        self.assertEqual(meaningful_line_count(STD), 3)


class BuildArtifactTests(unittest.TestCase):
    def macros(self):
        return [("VBA/Module1", "Module1.bas", STD), ("VBA/Sheet1", "Sheet1.cls", SHEET),
                ("VBA/ThisWorkbook", "ThisWorkbook.cls", WBOOK), ("VBA/Sheet2", "Sheet2.cls", EMPTY_SHEET),
                ("VBA/frmMain", "frmMain.frm", FORM)]

    def test_builds_valid_artifact(self):
        art = build_artifact("book.xlsm", self.macros(), [("AutoExec", "Workbook_Open", "Runs on open")], 20000)
        validate_artifact("vba_modules", art)
        self.assertEqual([m["name"] for m in art["modules"]], ["Module1", "Sheet1", "ThisWorkbook", "frmMain"])
        self.assertEqual({m["type"] for m in art["modules"]}, {"standard", "sheet", "workbook", "form"})
        self.assertEqual(len(art["findings"]), 1)
        self.assertTrue(any(f["code"] == "EMPTY_MODULES_SKIPPED" for f in art["flags"]))

    def test_crlf_normalised(self):
        art = build_artifact("b.xlsm", [("s", "M.bas", STD.replace("\n", "\r\n"))], [], 20000)
        self.assertNotIn("\r", art["modules"][0]["code"])

    def test_no_code_gives_warning_flag(self):
        art = build_artifact("b.xlsm", [("s", "Sheet2.cls", EMPTY_SHEET)], [], 20000)
        validate_artifact("vba_modules", art)
        self.assertEqual(art["modules"], [])
        self.assertEqual(art["flags"][0]["code"], "NO_CODE_MODULES")
        self.assertEqual(art["flags"][0]["severity"], "Warning")

    def test_line_limit_is_a_blocker(self):
        with self.assertRaises(BlockerError) as cm:
            build_artifact("b.xlsm", self.macros(), [], 5)
        self.assertIn("over the limit", str(cm.exception))

    def test_duplicate_names_renamed_and_flagged(self):
        art = build_artifact("b.xlsm", [("a", "M.bas", STD), ("b", "M2.bas", STD)], [], 20000)
        self.assertEqual([m["name"] for m in art["modules"]], ["Module1", "Module1_2"])
        self.assertEqual(art["flags"][0]["code"], "DUPLICATE_MODULE_NAME")

    def test_uninteresting_findings_dropped(self):
        art = build_artifact("b.xlsm", [("s", "M.bas", STD)], [("VBA string", "x", "y"), ("IOC", "http://a", "URL")], 20000)
        self.assertEqual([f["type"] for f in art["findings"]], ["IOC"])

    def test_missing_name_falls_back_to_file_stem(self):
        art = build_artifact("b.xlsm", [("s", "Fallback.bas", "Sub A()\nEnd Sub")], [], 20000)
        self.assertEqual(art["modules"][0]["name"], "Fallback")


if __name__ == "__main__":
    unittest.main()
