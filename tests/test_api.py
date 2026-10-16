"""API tests use a stub plugin, so they need fastapi + httpx but not langgraph or oletools."""
import tempfile
import time
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
    HAVE_API = True
except Exception:  # fastapi or httpx not installed
    HAVE_API = False

from app.core.plugin_registry import PluginRegistry
from app.core.settings import Settings
from app.plugins.base import PluginManifest, SkillPlugin
from app.plugins.xlsm_to_aspnetcore.intake import check_xlsm
from tests.helpers import make_zip


class _Graph:
    def __init__(self, ctx, gate):
        self.ctx, self.gate = ctx, gate

    def invoke(self, state):
        self.gate.wait(5)
        return {"flags": [], "error": None}


class StubPlugin(SkillPlugin):
    manifest = PluginManifest("stub", "Stub", "0", "a", "b", (".xlsm",))
    gate = None

    def stage_names(self, settings): return ["intake_check"]
    def validate_input(self, path, filename, max_bytes): return check_xlsm(path, filename, max_bytes)
    def initial_state(self, record, ctx): return {"run_id": record["run_id"]}
    def build_graph(self, ctx): return _Graph(ctx, StubPlugin.gate)


@unittest.skipUnless(HAVE_API, "fastapi/httpx not installed")
class ApiTests(unittest.TestCase):
    def setUp(self):
        import threading
        from app.main import create_app
        StubPlugin.gate = threading.Event()
        self.root = Path(tempfile.mkdtemp())
        self.app = create_app(Settings(workspace_root=self.root / "ws", max_upload_mb=1), PluginRegistry([StubPlugin()]))
        self.client = TestClient(self.app)
        self.xlsm = make_zip(self.root / "ok.xlsm").read_bytes()

    def tearDown(self):
        StubPlugin.gate.set()

    def post(self, data, name="ok.xlsm", skill="stub"):
        return self.client.post("/api/runs", data={"skill_id": skill}, files={"file": (name, data)})

    def test_spec_markdown_endpoint(self):
        from app.core.workspace import new_run_id
        c = self.app.state.container
        rid = new_run_id()
        c.workspace.create_run_dirs(rid)
        c.store.create(rid, "stub", "f.xlsm", ["a"])
        self.assertEqual(self.client.get(f"/api/runs/{rid}/spec.md").status_code, 404)
        (c.workspace.artifacts_dir(rid) / "migration_spec.md").write_text("# Migration specification\n", encoding="utf-8")
        r = self.client.get(f"/api/runs/{rid}/spec.md")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.text.startswith("# Migration specification"))
        self.assertEqual(self.client.get("/api/runs/..%2Fx/spec.md").status_code, 404)

    def test_app_file_endpoint(self):
        from app.core.workspace import new_run_id
        c = self.app.state.container
        rid = new_run_id()
        c.workspace.create_run_dirs(rid)
        c.store.create(rid, "stub", "f.xlsm", ["a"])
        app_dir = c.workspace.output_dir(rid) / "app"
        (app_dir / "X").mkdir(parents=True)
        (app_dir / "X" / "A.cs").write_text("class A {}", encoding="utf-8")
        (c.workspace.output_dir(rid) / "secret.txt").write_text("nope")
        ok = self.client.get(f"/api/runs/{rid}/app-file", params={"path": "X/A.cs"})
        self.assertEqual((ok.status_code, ok.text), (200, "class A {}"))
        for bad in ("../secret.txt", "X/missing.cs", "X", "/etc/passwd", ""):
            self.assertEqual(self.client.get(f"/api/runs/{rid}/app-file", params={"path": bad}).status_code, 404, bad)

    def test_skills(self):
        self.assertEqual(self.client.get("/api/skills").json()[0]["id"], "stub")

    def test_unknown_skill(self):
        r = self.post(self.xlsm, skill="nope")
        self.assertEqual((r.status_code, r.json()["code"]), (400, "unknown_skill"))

    def test_bad_files_create_no_run(self):
        self.assertEqual(self.post(self.xlsm, name="a.txt").status_code, 400)
        self.assertEqual(self.post(b"").status_code, 400)
        self.assertEqual(self.post(b"not a zip").status_code, 422)
        self.assertEqual(self.post(b"x" * (1024 * 1024 + 10)).status_code, 413)
        self.assertEqual(self.client.get("/api/runs").json(), [])

    def test_second_upload_during_run_gets_409(self):
        first = self.post(self.xlsm)
        self.assertEqual(first.status_code, 202)
        second = self.post(self.xlsm)
        self.assertEqual((second.status_code, second.json()["code"]), (409, "run_active"))
        StubPlugin.gate.set()
        run_id = first.json()["run_id"]
        for _ in range(50):
            if self.client.get(f"/api/runs/{run_id}").json()["status"] != "RUNNING":
                break
            time.sleep(0.1)
        self.assertEqual(self.client.get(f"/api/runs/{run_id}").json()["status"], "COMPLETED")
        self.assertEqual(self.post(self.xlsm).status_code, 202)  # slot is free again

    def test_unknown_run_and_artifact(self):
        self.assertEqual(self.client.get("/api/runs/" + "0" * 32).status_code, 404)
        self.assertEqual(self.client.get("/api/runs/..%2f..%2fetc").status_code, 404)
        run_id = self.post(self.xlsm).json()["run_id"]
        self.assertEqual(self.client.get(f"/api/runs/{run_id}/artifacts/vba_modules").json()["code"], "artifact_not_ready")
        self.assertEqual(self.client.get(f"/api/runs/{run_id}/artifacts/passwd").json()["code"], "artifact_unknown")


if __name__ == "__main__":
    unittest.main()
