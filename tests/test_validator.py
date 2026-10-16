import json
import tempfile
import unittest
from pathlib import Path

from app.core.context import PluginContext
from app.core.errors import BlockerError
from app.core.run_store import RunStore
from app.core.workspace import Workspace, new_run_id
from app.plugins.xlsm_to_aspnetcore.validator import parse_messages, validate_app, validator_stage
from tests.fakes import fake_settings

APP = Path("/tmp/x/app")
ERR = r"""/tmp/x/app/Demo/Services/BusinessRules.Rules.cs(12,5): error CS0103: The name 'foo' does not exist in the current context [/tmp/x/app/Demo/Demo.csproj]
/tmp/x/app/Demo/Services/BusinessRules.Rules.cs(12,5): error CS0103: The name 'foo' does not exist in the current context [/tmp/x/app/Demo/Demo.csproj]
/tmp/x/app/Demo/Program.cs(3,1): warning CS8618: Non-nullable property 'X' [/tmp/x/app/Demo/Demo.csproj]
C:\x\app\Demo\Pages\Index.cshtml(7,9): error CS1002: ; expected [C:\x\app\Demo\Demo.csproj]
  error NU1101: Unable to find package Foo. No packages exist with this id in source(s): nuget.org
"""


class ParseTests(unittest.TestCase):
    def test_errors_are_parsed_and_deduplicated(self):
        errors, warnings = parse_messages(ERR, APP)
        self.assertEqual(len(errors), 3)
        self.assertEqual(warnings, 1)
        first = errors[0]
        self.assertEqual((first["file"], first["line"], first["column"], first["code"]),
                         ("Demo/Services/BusinessRules.Rules.cs", 12, 5, "CS0103"))
        self.assertTrue(any(e["code"] == "NU1101" and "file" not in e for e in errors))

    def test_clean_output_has_no_errors(self):
        self.assertEqual(parse_messages("Build succeeded.\n    0 Warning(s)\n    0 Error(s)", APP), ([], 0))


def make_app(root: Path, name="Demo") -> Path:
    app = root / "app"
    app.mkdir(parents=True)
    (app / f"{name}.sln").write_text("sln")
    return app


class FakeDotnet:
    def __init__(self, restore=(0, "ok", False), build=(0, "Build succeeded.", False)):
        self.restore, self.build, self.calls = restore, build, []

    def __call__(self, args, cwd, timeout):
        self.calls.append(args[1:])
        if args[1] == "--version":
            return 0, "8.0.100\n", False
        return self.restore if args[1] == "restore" else self.build


MANIFEST = {"app_name": "Demo", "files": [{"path": "Demo/Services/BusinessRules.Rules.cs", "spec_refs": ["RUL-001"]}]}


class ValidateTests(unittest.TestCase):
    def run_it(self, runner):
        app = make_app(Path(tempfile.mkdtemp()))
        return validate_app(app, "Demo", MANIFEST, 30, runner=runner)

    def test_pass(self):
        runner = FakeDotnet()
        results, flags = self.run_it(runner)
        self.assertEqual(results["result"], "passed")
        self.assertEqual(results["dotnet_version"], "8.0.100")
        self.assertEqual([f["code"] for f in flags], ["BUILD_PASSED"])
        self.assertEqual(flags[0]["severity"], "Info")
        self.assertIn("--no-restore", runner.calls[-1])

    def test_build_failure_is_a_warning_with_spec_refs(self):
        app = make_app(Path(tempfile.mkdtemp()))
        line = f"{app}/Demo/Services/BusinessRules.Rules.cs(12,5): error CS0103: nope [p]"
        results, flags = validate_app(app, "Demo", MANIFEST, 30, runner=FakeDotnet(build=(1, line, False)))
        self.assertEqual(results["result"], "build_failed")
        self.assertEqual(results["errors"][0]["spec_refs"], ["RUL-001"])
        self.assertEqual(flags[0]["code"], "BUILD_FAILED")
        self.assertEqual(flags[0]["severity"], "Warning")
        self.assertEqual(flags[1]["code"], "BUILD_ERROR")

    def test_restore_failure_skips_build(self):
        runner = FakeDotnet(restore=(1, "error NU1301: Unable to load the service index", False))
        results, flags = self.run_it(runner)
        self.assertEqual(results["result"], "restore_failed")
        self.assertEqual(results["build"]["status"], "skipped")
        self.assertFalse(any(c[0] == "build" for c in runner.calls))
        self.assertEqual(flags[0]["code"], "RESTORE_FAILED")

    def test_timeout(self):
        results, flags = self.run_it(FakeDotnet(build=(None, "", True)))
        self.assertEqual(results["result"], "timed_out")
        self.assertEqual(flags[0]["code"], "BUILD_TIMED_OUT")

    def test_error_flags_are_capped(self):
        out = "\n".join(f"/tmp/x/app/Demo/A.cs({i},1): error CS1002: e{i} [p]" for i in range(1, 40))
        results, flags = self.run_it(FakeDotnet(build=(1, out, False)))
        self.assertEqual(sum(f["code"] == "BUILD_ERROR" for f in flags), 15)
        self.assertTrue(any(f["code"] == "BUILD_ERRORS_TRUNCATED" for f in flags))

    def test_missing_solution_is_a_blocker(self):
        with self.assertRaises(BlockerError):
            validate_app(Path(tempfile.mkdtemp()), "Demo", MANIFEST, 30, runner=FakeDotnet())


class StageTests(unittest.TestCase):
    def test_stage_writes_results(self):
        root = Path(tempfile.mkdtemp())
        ws, rid = Workspace(root), new_run_id()
        store = RunStore(ws)
        ws.create_run_dirs(rid)
        store.create(rid, "skill", "t.xlsm", ["validator"])
        make_app(ws.output_dir(rid))
        ws.artifact_path(rid, "generation_manifest").write_text(json.dumps(MANIFEST))
        ctx = PluginContext(fake_settings(workspace_root=root), store, ws, command_runner=FakeDotnet())
        out = validator_stage({"run_id": rid}, ctx)
        self.assertTrue(Path(out["validation_path"]).is_file())
        self.assertEqual(json.loads(ws.artifact_path(rid, "validation_results").read_text())["result"], "passed")
        self.assertIsNone(store.read(rid)["detail"])

    def test_stage_without_app_fails_clearly(self):
        root = Path(tempfile.mkdtemp())
        ws, rid = Workspace(root), new_run_id()
        store = RunStore(ws)
        ws.create_run_dirs(rid)
        store.create(rid, "skill", "t.xlsm", ["validator"])
        ctx = PluginContext(fake_settings(workspace_root=root), store, ws, command_runner=FakeDotnet())
        with self.assertRaises(BlockerError):
            validator_stage({"run_id": rid}, ctx)
