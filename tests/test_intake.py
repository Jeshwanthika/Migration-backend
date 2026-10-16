import tempfile
import unittest
from pathlib import Path

from app.plugins.xlsm_to_aspnetcore.intake import OLE_MAGIC, check_xlsm
from tests.helpers import make_zip

LIMIT = 10 * 1024 * 1024


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_valid(self):
        r = check_xlsm(make_zip(self.dir / "a.xlsm"), "a.xlsm", LIMIT)
        self.assertTrue(r.ok)

    def test_extension_case_insensitive(self):
        self.assertTrue(check_xlsm(make_zip(self.dir / "a.xlsm"), "BOOK.XLSM", LIMIT).ok)

    def test_wrong_extension(self):
        r = check_xlsm(make_zip(self.dir / "a.xlsx"), "a.xlsx", LIMIT)
        self.assertEqual((r.ok, r.http_status, r.code), (False, 400, "bad_extension"))

    def test_empty(self):
        p = self.dir / "e.xlsm"; p.write_bytes(b"")
        r = check_xlsm(p, "e.xlsm", LIMIT)
        self.assertEqual((r.http_status, r.code), (400, "empty_file"))

    def test_too_large(self):
        r = check_xlsm(make_zip(self.dir / "a.xlsm"), "a.xlsm", 10)
        self.assertEqual((r.http_status, r.code), (413, "file_too_large"))

    def test_corrupt(self):
        p = self.dir / "c.xlsm"; p.write_bytes(b"this is not a zip file at all")
        r = check_xlsm(p, "c.xlsm", LIMIT)
        self.assertEqual((r.http_status, r.code), (422, "corrupt_file"))

    def test_ole_container_is_encrypted_or_legacy(self):
        p = self.dir / "o.xlsm"; p.write_bytes(OLE_MAGIC + b"\x00" * 100)
        r = check_xlsm(p, "o.xlsm", LIMIT)
        self.assertEqual((r.http_status, r.code), (422, "encrypted_or_legacy"))

    def test_no_macros(self):
        p = make_zip(self.dir / "n.xlsm", names=("xl/workbook.xml",))
        r = check_xlsm(p, "n.xlsm", LIMIT)
        self.assertEqual((r.http_status, r.code), (422, "no_macros"))

    def test_not_a_workbook(self):
        p = make_zip(self.dir / "w.xlsm", names=("word/document.xml",))
        r = check_xlsm(p, "w.xlsm", LIMIT)
        self.assertEqual((r.http_status, r.code), (422, "not_a_workbook"))

    def test_missing_file(self):
        r = check_xlsm(self.dir / "nope.xlsm", "nope.xlsm", LIMIT)
        self.assertEqual(r.code, "missing_file")


if __name__ == "__main__":
    unittest.main()
