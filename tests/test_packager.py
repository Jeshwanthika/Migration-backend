import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.core.context import PluginContext
from app.core.errors import BlockerError
from app.core.run_store import RunStore
from app.core.workspace import Workspace, new_run_id
from app.plugins.xlsm_to_aspnetcore.packager import build_report, collect_app_files, is_excluded, packager_stage
from tests.fakes import fake_settings

SPEC = {"source_file": "Tracker.xlsm", "entities": [1], "rules": [1, 2], "screens": [], "workflows": [], "reports": [],
        "stubs": [{"module": "modX", "name": "Beep", "level": "unsupported", "reason": "SendKeys"}],
        "flags": [{"code": "SPEC_X", "severity": "Warning", "reason": "something"}]}
MANIFEST = {"app_name": "Tracker", "files": [{"path": "a"}], "stubs": [{"spec_id": "RUL-002", "method": "Beep", "cause": "unsupported", "reason": "no"}],
            "uncovered_spec_items": [], "flags": []}
FAILED = {"result": "build_failed", "dotnet_version": "8.0.1", "warning_count": 2,
          "restore": {"status": "ok"}, "build": {"status": "failed"},
          "errors": [{"code": "CS0103", "message": "bad name", "file": "Tracker/A.cs", "line": 3, "spec_refs": ["RUL-001"]}]}


def make_run(build_app=True, validation=None):
    root = Path(tempfile.mkdtemp())
    ws, rid = Workspace(root), new_run_id()
    store = RunStore(ws)
    ws.create_run_dirs(rid)
    store.create(rid, "skill", "Tracker.xlsm", ["packager"])
    ws.artifact_path(rid, "migration_spec").write_text(json.dumps(SPEC))
    ws.artifact_path(rid, "generation_manifest").write_text(json.dumps(MANIFEST))
    (ws.artifacts_dir(rid) / "migration_spec.md").write_text("# spec")
    if validation:
        ws.artifact_path(rid, "validation_results").write_text(json.dumps(validation))
    app = ws.output_dir(rid) / "app"
    if build_app:
        (app / "Tracker" / "bin" / "Debug").mkdir(parents=True)
        (app / "Tracker" / "obj").mkdir()
        (app / "Tracker" / "Program.cs").write_text("class P {}")
        (app / "Tracker.sln").write_text("sln")
        (app / "Tracker" / "bin" / "Debug" / "Tracker.dll").write_text("binary")
        (app / "Tracker" / "obj" / "x.json").write_text("{}")
        (app / ".env").write_text("GEMINI_API_KEY=secret")
        (app / "Tracker" / "Data.user").write_text("x")
    return ws, store, rid, PluginContext(fake_settings(workspace_root=root), store, ws)


class ExclusionTests(unittest.TestCase):
    def test_excluded_names(self):
        for p in ("Tracker/bin/Debug/a.dll", "obj/x.json", ".env", "sub/.env.local", "A.csproj.user", ".vs/x"):
            self.assertTrue(is_excluded(Path(p)), p)
        for p in ("Tracker/Program.cs", "Tracker/Binder.cs", "environment.md"):
            self.assertFalse(is_excluded(Path(p)), p)


class ReportTests(unittest.TestCase):
    def report(self, validation):
        flags = SPEC["flags"] + [{"code": "BUILD_ERROR", "severity": "Warning", "reason": "dup"}]
        return build_report(source_file="Tracker.xlsm", spec=SPEC, manifest=MANIFEST, validation=validation, flags=flags, files_in_zip=7, tokens=1234)

    def test_failed_build_is_stated_plainly(self):
        text = self.report(FAILED)
        self.assertIn("does not compile", text)
        self.assertIn("CS0103", text)
        self.assertIn("RUL-001", text)
        self.assertIn("modX.Beep", text)
        self.assertIn("RUL-002", text)
        self.assertNotIn("dup", text)  # BUILD_ERROR flags are listed once, under Build result

    def test_not_built(self):
        self.assertIn("was not built", self.report(None))

    def test_passed(self):
        ok = dict(FAILED, result="passed", errors=[], build={"status": "ok"})
        self.assertIn("builds", self.report(ok))


class StageTests(unittest.TestCase):
    def test_zip_contents_and_exclusions(self):
        ws, store, rid, ctx = make_run(validation=FAILED)
        out = packager_stage({"run_id": rid}, ctx)
        names = set(zipfile.ZipFile(out["zip_path"]).namelist())
        self.assertIn("MIGRATION_REPORT.md", names)
        self.assertIn("app/Tracker/Program.cs", names)
        self.assertIn("app/Tracker.sln", names)
        self.assertIn("docs/migration_spec.md", names)
        self.assertIn("docs/validation_results.json", names)
        self.assertFalse([n for n in names if "/bin/" in n or "/obj/" in n or ".env" in n or n.endswith(".user")])
        self.assertEqual(out["flags"][0]["code"], "PACKAGED")
        self.assertEqual(out["flags"][0]["severity"], "Info")
        self.assertTrue((ws.artifacts_dir(rid) / "MIGRATION_REPORT.md").is_file())
        self.assertFalse(list(ws.output_dir(rid).glob("*.part")))

    def test_failed_build_is_still_packaged(self):
        ws, store, rid, ctx = make_run(validation=FAILED)
        out = packager_stage({"run_id": rid, "flags": []}, ctx)
        report = zipfile.ZipFile(out["zip_path"]).read("MIGRATION_REPORT.md").decode()
        self.assertIn("does not compile", report)

    def test_no_secret_in_any_file(self):
        ws, store, rid, ctx = make_run(validation=FAILED)
        out = packager_stage({"run_id": rid}, ctx)
        z = zipfile.ZipFile(out["zip_path"])
        self.assertFalse(any(b"secret" in z.read(n) for n in z.namelist()))

    def test_missing_app_is_a_blocker(self):
        ws, store, rid, ctx = make_run(build_app=False)
        with self.assertRaises(BlockerError):
            packager_stage({"run_id": rid}, ctx)

    def test_collect_skips_symlinks(self):
        ws, store, rid, ctx = make_run()
        app = ws.output_dir(rid) / "app"
        try:
            (app / "link.txt").symlink_to(Path(tempfile.mkdtemp()) / "x")
        except OSError:
            self.skipTest("symlinks not available")
        self.assertNotIn(Path("link.txt"), collect_app_files(app))
