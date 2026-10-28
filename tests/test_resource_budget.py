"""Verify the shared 8 GB cap, safe previews, and resource monitoring."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

import resources
from scripts import install_8gb_budget as budget


class BudgetTests(unittest.TestCase):
    def test_manifest_only_targets_three_esn_units_and_slice(self):
        with tempfile.TemporaryDirectory() as td:
            files = budget.manifest(Path(td))
            self.assertEqual(len(files), 4)
            self.assertEqual({k.name for k in files}, {"esn-jarvis.slice", "90-esn-budget.conf"})
            self.assertTrue(all("wings" not in str(p) and "nginx" not in str(p) for p in files))
            self.assertEqual(sum("Slice=esn-jarvis.slice" in v for v in files.values()), 3)
            self.assertIn("MemoryMax=8G", files[Path(td)/"esn-jarvis.slice"])
            self.assertIn("MemoryHigh=7G", files[Path(td)/"esn-jarvis.slice"])

    def test_conflicting_existing_unit_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            files = budget.manifest(Path(td))
            collision = next(iter(files))
            collision.write_text("existing operator configuration")
            with self.assertRaises(RuntimeError):
                budget.preflight(files)
            self.assertEqual(collision.read_text(), "existing operator configuration")

    def test_apply_refuses_nonroot_before_writing(self):
        with tempfile.TemporaryDirectory() as td:
            files = budget.manifest(Path(td))
            with patch.object(budget.os, "geteuid", return_value=1001), self.assertRaises(RuntimeError):
                budget.apply(files)
            self.assertFalse(any(p.exists() for p in files))

    def test_apply_writes_only_budget_files_never_restarts_services(self):
        with tempfile.TemporaryDirectory() as td:
            files = budget.manifest(Path(td))
            runner = Mock()
            with patch.object(budget.os, "geteuid", return_value=0):
                budget.apply(files, runner=runner)
            self.assertTrue(all(p.read_text() == contents for p, contents in files.items()))
            calls = [args[0][0] for args in runner.call_args_list]
            self.assertEqual(calls.count(["systemctl", "daemon-reload"]), 1)
            self.assertFalse(any("restart" in cmd for cmd in calls))

    def test_monitor_reports_real_cgroup_numbers(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p/"memory.current").write_text(str(2*1024**3))
            (p/"memory.max").write_text(str(8*1024**3))
            (p/"memory.high").write_text(str(7*1024**3))
            (p/"memory.events").write_text("high 0\nmax 0\noom 0\noom_kill 0\n")
            s = resources.snapshot(p)
            self.assertTrue(s["shared_cap_active"])
            self.assertEqual(s["usage_percent"],25.0)
            self.assertEqual(s["events"]["oom_kill"],0)

    def test_monitor_is_honest_when_not_applied(self):
        with tempfile.TemporaryDirectory() as td:
            s = resources.snapshot(Path(td)/"not-installed")
            self.assertFalse(s["shared_cap_active"])
            self.assertIsNone(s["used_bytes"])


if __name__=="__main__":
    unittest.main()
