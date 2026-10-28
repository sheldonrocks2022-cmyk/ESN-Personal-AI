"""Non-destructive local Jarvis storage diagnostics and permission-boundary tests."""
from collections import namedtuple
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import os
import tempfile
import threading
import time
import unittest

import autonomous
import jarvis
import maintenance
import operations

DU = namedtuple("DU", "total used free")
GIB = 1024 ** 3


class StorageAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / "jarvis"
        (self.base / "cache").mkdir(parents=True)
        (self.base / "tmp").mkdir()

    def test_age_estimate_uses_only_owned_dirs(self):
        old = self.base / "cache" / "old.dat"
        old.write_bytes(b"x" * 31)
        os.utime(old, (time.time() - maintenance.AGE_SECONDS - 100,) * 2)
        new = self.base / "tmp" / "new.dat"
        new.write_bytes(b"y" * 11)
        summary = maintenance.cache_summary(self.base)
        self.assertEqual(summary["files_checked"], 2)
        self.assertEqual(summary["older_than_7_days_file_count"], 1)
        self.assertEqual(summary["older_than_7_days_bytes"], 31)
        self.assertFalse(summary["truncated"])

    def test_never_follow_symlinks_outside_owned_cache(self):
        outside = Path(self.temp.name) / "customer"
        outside.mkdir()
        (outside / "secret.txt").write_bytes(b"secret" * 999)
        (self.base / "cache" / "linked").symlink_to(outside, target_is_directory=True)
        summary = maintenance.cache_summary(self.base)
        self.assertEqual(summary["files_checked"], 0)
        self.assertEqual(summary["total_regular_file_bytes"], 0)
        other = Path(self.temp.name) / "linked-root"
        other.symlink_to(outside, target_is_directory=True)
        self.assertTrue(maintenance.cache_summary(other)["truncated"])

    def test_mount_summary_correct_and_does_not_delete(self):
        fake = DU(100 * GIB, 91 * GIB, 9 * GIB)
        with patch.object(maintenance.shutil, "disk_usage", return_value=fake):
            with patch.object(os, "remove", side_effect=AssertionError("No deletions allowed")):
                with patch.object(os, "unlink", side_effect=AssertionError("No deletions allowed")):
                    result = maintenance.report(cache_base=self.base)
        self.assertEqual(result["free_percent"], 9.0)
        self.assertEqual(result["disk_pressure"], "critical")
        self.assertFalse(result["cleanup_executed"])
        self.assertEqual(result["remote_nodes_checked"], 0)
        self.assertEqual(result["scope"], "local_jarvis_vps_only")
        self.assertNotIn("secret", str(result))

    def test_read_only_task_is_real_and_disallows_user_paths(self):
        folder = Path(self.temp.name) / "database.sqlite"
        with patch.object(jarvis, "DB_PATH", str(folder)):
            ident = operations.enqueue("storage_audit")
            with self.assertRaises(ValueError):
                operations.enqueue("storage_audit", {"target": "/var/lib/pterodactyl/volumes"})
            fake = {"scope": "local_jarvis_vps_only", "free_percent": 21.0}
            with patch.object(maintenance, "report", return_value=fake) as report:
                self.assertTrue(operations.tick())
                report.assert_called_once_with()
            entry = next(x for x in operations.jobs() if x["id"] == ident)
            self.assertEqual(entry["status"], "completed")
            self.assertIn('"free_percent": 21.0', entry["result_json"])

    def test_autonomous_plan_correctly_scopes_local_disk(self):
        self.assertEqual(autonomous.steps_for_goal("Audit disk space on Jarvis"), ["storage_audit"])
        self.assertEqual(autonomous.steps_for_goal("Check ESN node disk space"), ["storage_audit"])
        for prompt in ("Audit disk across all nodes", "Check each node disk", "Audit the four nodes storage"):
            with self.subTest(prompt=prompt), self.assertRaises(ValueError):
                autonomous.steps_for_goal(prompt)

    def test_protected_wings_paths_never_selected(self):
        paths = str(maintenance.CACHE_BASE) + "/cache " + str(maintenance.CACHE_BASE) + "/tmp"
        for protected in maintenance.PROTECTED:
            self.assertNotIn(protected, paths)
        with self.assertRaises(ValueError):
            autonomous.steps_for_goal("Delete Pterodactyl backups and clean disk space")

    def test_inspection_bounded(self):
        for i in range(8):
            (self.base / "cache" / f"f{i}").write_text("x")
        with patch.object(maintenance, "MAX_FILES", 3):
            result = maintenance.cache_summary(self.base)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["files_checked"], 3)


class StorageAuditApiTests(unittest.TestCase):
    def test_owner_only_http_endpoint(self):
        token = "fake-owner-token-for-storage-test-123456789"
        with patch.object(jarvis, "OWNER_TOKEN", token):
            server = ThreadingHTTPServer(("127.0.0.1", 0), jarvis.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = "http://127.0.0.1:" + str(server.server_port)
            try:
                with self.assertRaises(HTTPError) as denied:
                    urlopen(base + "/api/operations/storage", timeout=5)
                self.assertEqual(denied.exception.code, 401)
                fake = {"scope": "local_jarvis_vps_only", "free_percent": 88}
                with patch.object(maintenance, "report", return_value=fake):
                    req = Request(base + "/api/operations/storage", headers={"Authorization": "Bearer " + token})
                    with urlopen(req, timeout=5) as response:
                        self.assertEqual(response.status, 200)
                        self.assertIn(b"local_jarvis_vps_only", response.read())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
