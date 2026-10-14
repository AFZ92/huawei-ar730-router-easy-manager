"""Offline regression tests for distributed writes, recovery and the actual Qt timer."""
import copy
import io
import urllib.error
import urllib.parse
from unittest.mock import patch
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
APPDIR = Path(__file__).resolve().parent.parent
WORK = tempfile.mkdtemp(prefix="ar730-firebase-tests-")
for filename in ("ar730_manager.py", "ar730_qt.py", "release_update.py", "firebase_merge.py"):
    shutil.copy(APPDIR / filename, WORK)
shutil.copytree(APPDIR / "assets", Path(WORK) / "assets")
sys.path.insert(0, WORK)
sys.argv[0] = str(Path(WORK) / "ar730_qt.py")
import firebase_merge as merge
import ar730_qt as qt
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])


class Store:
    def __init__(self, state=None):
        self.state = copy.deepcopy(state)
        self.version = 1
        self.archives = []
        self.before_commit = None
        self.fail_after_commit = False
        self.offline = False
        self.writes = 0


class Transport:
    DB_KEYS = merge.DB_KEYS
    def __init__(self, store, settings=None):
        self.store, self.settings = store, settings or {}
    def configured(self): return True
    def _url(self): return "fake://project/default/shared_state"
    def pull(self):
        if self.store.offline:
            raise RuntimeError("offline")
        if self.store.state is None:
            return None
        state = copy.deepcopy(self.store.state)
        state["_update_time"] = str(self.store.version)
        state["saved_at"] = "version-" + str(self.store.version)
        return state
    def archive(self, state):
        if self.store.offline: raise RuntimeError("offline")
        self.store.archives.append(copy.deepcopy(state))
    def commit(self, state, version):
        if self.store.before_commit:
            callback, self.store.before_commit = self.store.before_commit, None
            callback()
        expected = str(self.store.version) if self.store.state is not None else None
        if expected != version:
            raise qt.legacy.FirebaseRequestError(400, "contention", "FAILED_PRECONDITION")
        self.archive(state)
        self.store.state = copy.deepcopy(state)
        self.store.version += 1
        self.store.writes += 1
        if self.store.fail_after_commit:
            self.store.fail_after_commit = False
            raise RuntimeError("connection lost after successful write")
        return "version-" + str(self.store.version)


def state(records=None):
    data = merge.snapshot({}, {})
    data["db"]["devices"] = copy.deepcopy(records or {})
    return merge.validate(data)


class MergeTests(unittest.TestCase):
    def test_concurrent_additions_retry_and_converge(self):
        base = state()
        store = Store(base)
        a, b = state({"a": {"name": "A"}}), state({"b": {"name": "B"}})
        store.before_commit = lambda: merge.synchronize(Transport(store), b, base)
        merged = merge.synchronize(Transport(store), a, base)["state"]
        self.assertEqual(set(merged["db"]["devices"]), {"a", "b"})
        self.assertEqual(merged, store.state)

    def test_first_sync_retains_existing_local_and_cloud_data(self):
        store = Store(state({"remote": {"name": "R"}}))
        result = merge.synchronize(Transport(store), state({"local": {"name": "L"}}))
        self.assertEqual(set(result["state"]["db"]["devices"]), {"remote", "local"})
        self.assertTrue(store.archives)

    def test_independent_fields_merge(self):
        base = state({"a": {"name": "old", "note": "old"}})
        local, remote = copy.deepcopy(base), copy.deepcopy(base)
        local["db"]["devices"]["a"]["name"] = "new name"
        remote["db"]["devices"]["a"]["note"] = "new note"
        result, conflicts = merge.merge(base, local, remote)
        self.assertEqual(result["db"]["devices"]["a"], {"name": "new name", "note": "new note"})
        self.assertFalse(conflicts)

    def test_conflicting_values_both_archived(self):
        base = state({"a": {"name": "old"}})
        local, remote = state({"a": {"name": "A"}}), state({"a": {"name": "B"}})
        store = Store(remote)
        result = merge.synchronize(Transport(store), local, base)
        self.assertEqual(result["state"]["db"]["devices"]["a"]["name"], "B")
        self.assertTrue(result["conflicts"])
        self.assertIn(local, store.archives)

    def test_deletion_and_stale_install_do_not_resurrect(self):
        base = state({"a": {"name": "old"}})
        store = Store(base)
        deleted = merge.synchronize(Transport(store), state(), base)["state"]
        self.assertNotIn("a", deleted["db"]["devices"])
        result = merge.synchronize(Transport(store), base)["state"]
        self.assertNotIn("a", result["db"]["devices"])
        self.assertTrue(result["deleted"])

    def test_explicit_recreation_after_acknowledged_delete(self):
        base = state()
        base["deleted"] = ['["devices","a"]']
        local = copy.deepcopy(base)
        local["db"]["devices"]["a"] = {"name": "new"}
        result, unused = merge.merge(base, local, base)
        self.assertIn("a", result["db"]["devices"])
        self.assertFalse(result["deleted"])

    def test_ambiguous_commit_retries_without_duplicate_history(self):
        local = state({"a": {"name": "A"}})
        local["db"]["history"] = [{"id": "event-a", "when": "now", "action": "add"}]
        store = Store(state())
        store.fail_after_commit = True
        with self.assertRaises(RuntimeError):
            merge.synchronize(Transport(store), local, state())
        result = merge.synchronize(Transport(store), local, state())
        self.assertEqual(len(result["state"]["db"]["history"]), 1)
        self.assertEqual(store.writes, 1)

    def test_malformed_remote_never_overwrites(self):
        store = Store({"db": {"devices": []}})
        with self.assertRaises(ValueError):
            merge.synchronize(Transport(store), state({"a": {}}))
        self.assertEqual(store.writes, 0)

    def test_backup_failure_prevents_commit(self):
        store = Store(state())
        transport = Transport(store)
        transport.archive = lambda data: (_ for _ in ()).throw(RuntimeError("backup denied"))
        with self.assertRaises(RuntimeError):
            merge.synchronize(transport, state({"a": {"name": "A"}}))
        self.assertEqual(store.writes, 0)

    def test_nested_deletions_are_not_resurrected_by_stale_install(self):
        base = state({"a": {"name": "A", "old_note": "remove"}})
        base["settings"] = {"withdrawn_lines": {"gateway": {"reason": "manual"}}}
        local = copy.deepcopy(base)
        local["db"]["devices"]["a"].pop("old_note")
        local["settings"]["withdrawn_lines"].clear()
        store = Store(base)
        merge.synchronize(Transport(store), local, base)
        result = merge.synchronize(Transport(store), base)
        self.assertNotIn("old_note", result["state"]["db"]["devices"]["a"])
        self.assertEqual(result["state"]["settings"]["withdrawn_lines"], {})

    def test_incomplete_remote_is_rejected(self):
        store = Store({"db": {"devices": {}}})
        with self.assertRaises(ValueError):
            merge.synchronize(Transport(store), state({"a": {"name": "A"}}), state())
        self.assertEqual(store.writes, 0)

    def test_continuous_contention_leaves_input_unchanged(self):
        local = state({"a": {"name": "A"}})
        before = copy.deepcopy(local)
        store = Store(state())
        transport = Transport(store)
        def reject(state, version):
            raise qt.legacy.FirebaseRequestError(409, "busy")
        transport.commit = reject
        with self.assertRaises(RuntimeError):
            merge.synchronize(transport, local, state())
        self.assertEqual(before, local)
        self.assertEqual(store.writes, 0)

    def test_settings_secrets_and_local_preferences_are_not_shared(self):
        settings = {"firebase_password": "secret", "mac_shared_password": "secret",
                    "username": "admin", "qt_ui_lang": "ar", "host": "private",
                    "default_mac_group": "grp_team"}
        self.assertEqual(merge.snapshot({}, settings)["settings"], {"default_mac_group": "grp_team"})


class RestTransportTests(unittest.TestCase):
    def test_version_preconditions_and_private_metadata_filter(self):
        transport = qt.legacy.FirebaseSync({"firebase_project_id": "test-project"})
        transport._token = lambda: "test-token"
        calls = []
        def request(url, **kwargs):
            if kwargs.get("method", "GET") == "GET":
                raise qt.legacy.FirebaseRequestError(404, "missing")
            calls.append((url, kwargs))
            return {}
        transport._request = request
        local = state({"a": {"name": "A"}})
        transport.commit(local, "2026-10-14T12:00:00.123456Z")
        revision_url, archive_request = calls[0]
        self.assertIn("/documents/ar730_manager_revisions/", revision_url)
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(revision_url).query),
                         {"currentDocument.exists": ["false"]})
        main_url, request = calls[-1]
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(main_url).query),
                         {"currentDocument.updateTime": ["2026-10-14T12:00:00.123456Z"],
                          "updateMask.fieldPaths": ["state"]})
        self.assertEqual(request["method"], "PATCH")
        self.assertEqual(transport._value(request["payload"]["fields"]["state"])["schema_version"], 2)
        calls.clear()
        transport.commit(local, None)
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(calls[-1][0]).query),
                         {"currentDocument.exists": ["false"], "updateMask.fieldPaths": ["state"]})

    def test_existing_revision_must_match(self):
        transport = qt.legacy.FirebaseSync({"firebase_project_id": "test-project"})
        transport._token = lambda: "test-token"
        def request(url, method="GET", **unused):
            if method == "PATCH":
                raise qt.legacy.FirebaseRequestError(400, "exists", "FAILED_PRECONDITION")
            return {"fields": {"state": transport._field(state({"other": {}}))}}
        transport._request = request
        with self.assertRaises(RuntimeError):
            transport.archive(state({"a": {"name": "A"}}))

    def test_http_error_exposes_retryable_status_without_secret_body(self):
        transport = qt.legacy.FirebaseSync({})
        error = urllib.error.HTTPError("https://example.invalid", 400, "bad", {},
            io.BytesIO(b'{"error":{"status":"FAILED_PRECONDITION","message":"private content"}}'))
        with patch.object(qt.legacy.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(qt.legacy.FirebaseRequestError) as caught:
                transport._request("https://example.invalid")
        self.assertEqual(caught.exception.status, "FAILED_PRECONDITION")
        self.assertNotIn("private content", str(caught.exception))


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(state())
        self.original = qt.legacy.FirebaseSync
        store = self.store
        qt.legacy.FirebaseSync = lambda settings: Transport(store, copy.deepcopy(settings))
        self.settings_path = os.path.join(WORK, self._testMethodName + "-settings.json")
        self.db_path = os.path.join(WORK, self._testMethodName + "-db.json")
        qt.legacy.SETTINGS_FILE = self.settings_path
        qt.legacy.DB_FILE = self.db_path
        # Avoid any real updater request while exercising Qt's actual event loop.
        self.original_update = qt.legacy.check_for_update
        qt.legacy.check_for_update = lambda version: None
        qt.legacy.atomic_json_write(self.settings_path, {"storage_mode": "firebase"})
        self.controller = qt.ReadController()
        self.controller.settings = {"storage_mode": "firebase"}
        self.controller.firebase = Transport(store, self.controller.settings)

    def tearDown(self):
        self.controller.close()
        qt.legacy.FirebaseSync = self.original
        qt.legacy.check_for_update = self.original_update

    def test_offline_changes_survive_restart(self):
        self.assertTrue(self.controller.firebase_sync().ok)
        self.store.offline = True
        self.controller.db.upsert_device("a", "Offline", "grp_staff")
        self.assertFalse(self.controller.firebase_sync().ok)
        self.controller.close()
        self.controller = qt.ReadController()
        self.store.offline = False
        self.assertTrue(self.controller.firebase_sync().ok)
        self.assertEqual(self.store.state["db"]["devices"]["a"]["name"], "Offline")
        self.assertTrue(Path(self.db_path + ".bak").exists())

    def test_edits_during_request_stay_pending(self):
        self.controller.db.upsert_device("a", "first", "grp_staff")
        job = self.controller.firebase_job()
        result = job["run"]()
        self.controller.db.set_device_meta("a", "later", "note")
        self.controller.firebase_accept(job, result)
        self.assertEqual(self.controller.db.device("a")["name"], "later")
        self.assertTrue(self.controller._firebase_dirty)
        self.assertTrue(self.controller.firebase_sync().ok)
        self.assertEqual(self.store.state["db"]["devices"]["a"]["name"], "later")

    def test_project_change_ignores_old_response(self):
        job = self.controller.firebase_job()
        result = job["run"]()
        self.controller.settings["storage_mode"] = "local"
        before = copy.deepcopy(self.controller.db.data)
        self.assertFalse(self.controller.firebase_accept(job, result).ok)
        self.assertEqual(before, self.controller.db.data)

    def test_actual_qt_background_timer_uploads_and_downloads(self):
        window = qt.MainWindow(self.controller)
        window.show()
        def wait_for(predicate, seconds=8):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                app.processEvents()
                if predicate(): return
                time.sleep(.01)
            self.fail("background synchronization timed out")
        try:
            wait_for(lambda: merge.META_KEY in self.controller.db.data)
            self.controller.db.upsert_device("a", "A", "grp_staff")
            window._next_cloud_poll = 0
            wait_for(lambda: "a" in self.store.state["db"]["devices"] and not self.controller._firebase_dirty)
            base = copy.deepcopy(self.store.state)
            other = copy.deepcopy(base)
            other["db"]["devices"]["b"] = {"name": "B"}
            merge.synchronize(Transport(self.store), other, base)
            window._next_cloud_poll = 0
            wait_for(lambda: self.controller.db.device("b") is not None)
            self.assertEqual(self.controller.db.device("a")["name"], "A")
        finally:
            window.close()
            for unused in range(100):
                app.processEvents()
                if not any(w.isRunning() for w in window.workers): break
                time.sleep(.01)

    def test_failed_local_replacement_preserves_pending_changes(self):
        self.controller.firebase_sync()
        self.controller.db.upsert_device("a", "Pending", "grp_staff")
        before = Path(self.db_path).read_bytes()
        job = self.controller.firebase_job()
        result = job["run"]()
        with patch.object(qt.legacy.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.controller.firebase_accept(job, result)
        self.assertEqual(Path(self.db_path).read_bytes(), before)
        self.assertEqual(self.controller.db.device("a")["name"], "Pending")
        self.assertTrue(self.controller.firebase_sync().ok)

    def test_corrupt_local_file_is_preserved(self):
        Path(self.db_path).write_text('{"devices":')
        with self.assertRaises(RuntimeError):
            qt.legacy.LocalDB(self.db_path)
        self.assertEqual(Path(self.db_path).read_text(), '{"devices":')


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
