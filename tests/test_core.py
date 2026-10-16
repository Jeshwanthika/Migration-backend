import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from app.core.context import PluginContext
from app.core.errors import BlockerError
from app.core.models import has_warnings, new_flag, utc_now
from app.core.run_store import RunStore
from app.core.settings import Settings
from app.core.stage_runner import route_after_stage, run_stage
from app.core.workspace import Workspace, is_valid_run_id, new_run_id


def make_env():
    root = Path(tempfile.mkdtemp())
    ws = Workspace(root)
    store = RunStore(ws)
    ctx = PluginContext(Settings(workspace_root=root), store, ws)
    run_id = new_run_id()
    ws.create_run_dirs(run_id)
    store.create(run_id, "skill", "f.xlsm", ["a", "b"])
    return ws, store, ctx, run_id


class RunStoreTests(unittest.TestCase):
    def test_create_and_read(self):
        ws, store, ctx, rid = make_env()
        rec = store.read(rid)
        self.assertEqual(rec["status"], "RUNNING")
        self.assertEqual([n["status"] for n in rec["nodes"]], ["pending", "pending"])

    def test_bad_run_id_is_rejected(self):
        ws, store, ctx, rid = make_env()
        self.assertIsNone(store.read("../etc"))
        self.assertFalse(is_valid_run_id("../x"))
        with self.assertRaises(ValueError):
            ws.run_dir("../x")

    def test_failed_finish_skips_pending_nodes(self):
        ws, store, ctx, rid = make_env()
        store.set_node(rid, "a", "running"); store.set_node(rid, "a", "failed")
        rec = store.finish(rid, "FAILED", error={"node": "a", "message": "boom"})
        self.assertEqual([n["status"] for n in rec["nodes"]], ["failed", "skipped"])
        self.assertIsNone(rec["current_node"])

    def test_interrupted_runs_marked_failed(self):
        ws, store, ctx, rid = make_env()
        self.assertEqual(store.mark_interrupted(), [rid])
        self.assertEqual(store.read(rid)["status"], "FAILED")


class StageRunnerTests(unittest.TestCase):
    def test_success_updates_node_and_counts_flags(self):
        ws, store, ctx, rid = make_env()
        flag = new_flag("X", "Info", "r")
        out = run_stage("a", lambda s, c: {"flags": [flag], "tokens_used": 5}, {"run_id": rid}, ctx)
        rec = store.read(rid)
        self.assertEqual(rec["nodes"][0]["status"], "done")
        self.assertEqual((rec["flags_count"], rec["tokens_used"]), (1, 5))
        self.assertEqual(route_after_stage(out), "continue")

    def test_blocker_stops_the_run(self):
        ws, store, ctx, rid = make_env()
        def boom(s, c): raise BlockerError("bad thing")
        out = run_stage("a", boom, {"run_id": rid}, ctx)
        self.assertEqual(route_after_stage(out), "stop")
        self.assertEqual(store.read(rid)["error"], {"node": "a", "message": "bad thing"})
        self.assertEqual(store.read(rid)["nodes"][0]["status"], "failed")

    def test_unexpected_exception_does_not_escape(self):
        ws, store, ctx, rid = make_env()
        def boom(s, c): raise KeyError("oops")
        out = run_stage("a", boom, {"run_id": rid}, ctx)
        self.assertEqual(route_after_stage(out), "stop")
        self.assertIn("KeyError", out["error"]["message"])


class WorkspaceTests(unittest.TestCase):
    def test_cleanup_deletes_only_old_finished_runs(self):
        ws, store, ctx, old = make_env()
        store.finish(old, "COMPLETED")
        store.update(old, finished_at=(utc_now() - timedelta(days=30)).isoformat())
        fresh = new_run_id(); ws.create_run_dirs(fresh); store.create(fresh, "s", "f", ["a"]); store.finish(fresh, "COMPLETED")
        running = new_run_id(); ws.create_run_dirs(running); store.create(running, "s", "f", ["a"])
        store.update(running, started_at=(utc_now() - timedelta(days=30)).isoformat())
        deleted = ws.cleanup_expired(store, 7)
        self.assertEqual(deleted, [old])
        self.assertFalse(ws.run_dir(old).exists())
        self.assertTrue(ws.run_dir(fresh).exists())
        self.assertTrue(ws.run_dir(running).exists())


class SettingsAndFlagsTests(unittest.TestCase):
    def test_defaults_match_approved_limits(self):
        s = Settings(workspace_root=Path("."))
        self.assertEqual((s.max_upload_mb, s.max_vba_lines), (10, 20000))
        self.assertNotIn("api", repr(Settings(workspace_root=Path("."), gemini_api_key="SECRET")).lower().replace("gemini_api_key", ""))

    def test_has_warnings(self):
        self.assertFalse(has_warnings([new_flag("a", "Info", "r")]))
        self.assertTrue(has_warnings([new_flag("a", "Warning", "r")]))
        self.assertFalse(has_warnings([]))


if __name__ == "__main__":
    unittest.main()


class SafeChildTests(unittest.TestCase):
    def test_only_files_inside_root(self):
        from app.core.files import safe_child
        root = Path(tempfile.mkdtemp())
        (root / "app").mkdir()
        (root / "app" / "a.txt").write_text("x")
        (root / "secret.txt").write_text("y")
        app = root / "app"
        self.assertEqual(safe_child(app, "a.txt"), (app / "a.txt").resolve())
        for bad in ("../secret.txt", "missing.txt", "", ".", "..", str(root / "secret.txt"), "a.txt\x00"):
            self.assertIsNone(safe_child(app, bad), bad)
