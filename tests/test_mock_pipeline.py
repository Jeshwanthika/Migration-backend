import json
import tempfile
import unittest
from pathlib import Path

from app.core.context import PluginContext
from app.core.llm.mock import MockProvider
from app.core.run_store import RunStore
from app.core.workspace import Workspace, new_run_id
from app.plugins.xlsm_to_aspnetcore.analyzer import analyzer_stage
from app.plugins.xlsm_to_aspnetcore.generator import generator_stage
from app.plugins.xlsm_to_aspnetcore.packager import packager_stage
from app.plugins.xlsm_to_aspnetcore.spec_architect import spec_architect_stage
from tests.fakes import fake_settings

CODE = '''Attribute VB_Name = "modExp"
Option Explicit
Sub AddExpense(amt As Double)
    Cells(2, 1).Value = amt
End Sub
Function Total() As Double
    Total = 0
End Function'''


class MockPipelineTests(unittest.TestCase):
    def test_analyzer_spec_generator_run_offline(self):
        root = Path(tempfile.mkdtemp())
        ws = Workspace(root)
        store = RunStore(ws)
        rid = new_run_id()
        ws.create_run_dirs(rid)
        store.create(rid, "skill", "Mock Tracker.xlsm", ["analyzer"])
        vba = {"source_file": "Mock Tracker.xlsm", "modules": [{"name": "modExp", "type": "standard", "code": CODE,
                                                                  "line_count": CODE.count("\n") + 1}], "total_lines": CODE.count("\n") + 1}
        ws.artifact_path(rid, "vba_modules").write_text(json.dumps(vba))
        ctx = PluginContext(fake_settings(workspace_root=root), store, ws, llm_provider=MockProvider())
        state = {"run_id": rid}
        for stage in (analyzer_stage, spec_architect_stage, generator_stage, packager_stage):
            state.update(stage(state, ctx) or {})
        app = ws.output_dir(rid) / "app"
        self.assertTrue(list(app.rglob("*.sln")))
        self.assertTrue(list(app.rglob("Program.cs")))
        import zipfile
        names = zipfile.ZipFile(state["zip_path"]).namelist()
        self.assertIn("MIGRATION_REPORT.md", names)
        self.assertTrue(any(n.endswith("Program.cs") for n in names))
