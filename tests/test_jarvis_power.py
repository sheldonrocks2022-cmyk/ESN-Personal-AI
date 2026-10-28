"""Step 57 — reversible Jarvis power mode, no effects on customer services."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import install_power_command as installer
from scripts import jarvis_power as power


class FakeSystemd:
    def __init__(self, *, ollama_shared=False):
        self.units = {
            power.DISCORD: {"enabled": "enabled", "active": "active", "slice": power.JARVIS_SLICE},
            power.WEB: {"enabled": "enabled", "active": "active", "slice": power.JARVIS_SLICE},
            power.MODEL: {"enabled": "enabled", "active": "active",
                          "slice": "system.slice" if ollama_shared else power.JARVIS_SLICE},
        }
        self.calls = []

    def run(self, *args):
        self.calls.append(tuple(args))
        operation, *remaining = args
        if operation == "show":
            unit = remaining[0]
            prop = next((x for x in remaining if x.startswith("--property=")), "")
            result = ("loaded" if prop == "--property=LoadState"
                      else self.units[unit]["slice"])
            return subprocess.CompletedProcess(args, 0, result + "\n", "")
        if operation == "is-enabled":
            value = self.units[remaining[0]]["enabled"]
            return subprocess.CompletedProcess(args, 0 if value=="enabled" else 1, value+"\n", "")
        if operation == "is-active":
            value = self.units[remaining[0]]["active"]
            return subprocess.CompletedProcess(args, 0 if value=="active" else 3, value+"\n", "")
        if operation in ("enable", "disable"):
            unit = remaining[-1]
            self.units[unit]["enabled"] = "enabled" if operation=="enable" else "disabled"
            if "--now" in remaining:
                self.units[unit]["active"] = "inactive"
            return subprocess.CompletedProcess(args, 0, "", "")
        if operation == "start":
            self.units[remaining[0]]["active"] = "active"
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError("Unexpected systemctl call: " + str(args))


class PowerControlTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        self.patches = [
            patch.object(power, "STATE_DIR", root),
            patch.object(power, "STATE_FILE", root / "last-off.json"),
            patch.object(power, "LOCK_FILE", root / "power.lock"),
            patch.object(power, "_reported_resources"),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.fake = FakeSystemd()
        systemd_patch = patch.object(power, "systemctl", side_effect=self.fake.run)
        systemd_patch.start()
        self.addCleanup(systemd_patch.stop)
        power.prepare_dir()

    def test_off_disables_only_three_services_and_preserves_original_boot_state(self):
        power.off()
        self.assertTrue(power.STATE_FILE.exists())
        self.assertEqual(os.stat(power.STATE_FILE).st_mode & 0o777, 0o600)
        self.assertEqual([x for x in self.fake.calls if x[0]=="disable"],
                         [("disable","--now",power.DISCORD),
                          ("disable","--now",power.WEB),
                          ("disable","--now",power.MODEL)])
        self.assertTrue(all("wings" not in str(x) and "nginx" not in str(x)
                            and "docker" not in str(x) for x in self.fake.calls))
        for unit in power.SHUTDOWN_ORDER:
            self.assertEqual(self.fake.units[unit]["active"], "inactive")

    def test_off_then_on_restores_boot_configuration_and_services(self):
        self.fake.units[power.DISCORD]["enabled"] = "disabled"
        power.off()
        power.on()
        self.assertEqual(self.fake.units[power.MODEL]["active"], "active")
        self.assertEqual(self.fake.units[power.WEB]["active"], "active")
        self.assertEqual(self.fake.units[power.DISCORD]["active"], "active")
        self.assertEqual(self.fake.units[power.DISCORD]["enabled"], "disabled")
        self.assertFalse(power.STATE_FILE.exists())
        starts = [x for x in self.fake.calls if x[0] == "start"]
        self.assertEqual(starts, [("start",power.MODEL),("start",power.WEB),("start",power.DISCORD)])

    def test_repeated_off_does_not_replace_boot_snapshot(self):
        power.off()
        before = power.STATE_FILE.read_bytes()
        power.off()
        self.assertEqual(power.STATE_FILE.read_bytes(), before)

    def test_shared_ollama_refused_by_default_but_can_be_preserved(self):
        self.fake.units[power.MODEL]["slice"] = "system.slice"
        with self.assertRaisesRegex(RuntimeError, "potentially shared"):
            power.off()
        self.assertFalse(power.STATE_FILE.exists())
        power.off(keep_ollama=True)
        self.assertEqual(self.fake.units[power.MODEL]["active"], "active")
        self.assertNotIn(power.MODEL, power.read_state()["units"])
        power.on()
        self.assertEqual(self.fake.units[power.MODEL]["active"], "active")

    def test_dry_run_does_not_mutate_or_create_state(self):
        power.off(dry_run=True)
        self.assertFalse(power.STATE_FILE.exists())
        self.assertFalse(any(c[0] in ("disable", "enable", "start") for c in self.fake.calls))

    def test_refuse_on_without_saved_off_record(self):
        with self.assertRaisesRegex(RuntimeError,"No previously recorded"):
            power.on()
        self.assertFalse(any(x[0] == "start" for x in self.fake.calls))

    def test_off_then_on_cannot_change_ollama_selection(self):
        power.off(keep_ollama=True)
        with self.assertRaisesRegex(RuntimeError, "same option"):
            power.off(keep_ollama=False)

    def test_failures_keep_recovery_record(self):
        original = self.fake.run
        def fail(*cmd):
            if cmd[0] == "start" and cmd[-1] == power.WEB:
                return subprocess.CompletedProcess(cmd, 1, "", "test failure")
            return original(*cmd)
        power.off()
        with patch.object(power, "systemctl", side_effect=fail):
            with self.assertRaises(RuntimeError):
                power.on()
        self.assertTrue(power.STATE_FILE.exists())

    def test_state_file_symlink_refused(self):
        power.off()
        target = power.STATE_DIR / "fake"
        power.STATE_FILE.rename(target)
        power.STATE_FILE.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError,"symlinked"):
            power.read_state()

    def test_nonroot_cannot_execute_mutations(self):
        with patch.object(power.os, "geteuid", return_value=1001):
            self.assertEqual(power.main(["off"]), 1)
            self.assertEqual(power.main(["on"]), 1)
        self.assertFalse(power.STATE_FILE.exists())

    def test_status_is_only_read_only(self):
        power.status()
        self.assertFalse(any(c[0] in ("disable","enable","start") for c in self.fake.calls))


class InstallerTests(unittest.TestCase):
    def test_default_preview_does_not_write(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "esnjarvis"
            installer.install(path, apply=False)
            self.assertFalse(path.exists())

    def test_exclusive_install_and_idempotence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "esnjarvis"
            with patch.object(installer.os, "geteuid", return_value=0):
                installer.install(path, apply=True)
                installer.install(path, apply=True)
            self.assertEqual(path.read_text(), installer.WRAPPER)
            self.assertEqual(path.stat().st_mode & 0o777, 0o755)
            self.assertNotIn("wings", installer.WRAPPER)

    def test_refuse_to_replace_someone_elses_command(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "esnjarvis"
            path.write_text("existing administrator script")
            with self.assertRaisesRegex(RuntimeError,"Refusing to overwrite"):
                installer.install(path, apply=True)
            self.assertEqual(path.read_text(), "existing administrator script")


if __name__ == "__main__":
    unittest.main()
