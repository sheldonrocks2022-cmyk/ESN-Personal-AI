"""Regression tests for mobile-friendly encrypted vault -> panel environment sync."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from cryptography.fernet import Fernet
import connections
from scripts import sync_panel_key_from_vault as vaultsync

KEY = "ptla_" + "A" * 50


class FakeResponse:
    status = 200
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, *args): return b'{"object":"list","data":[]}'


class VaultSyncTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.env = root / "esn-jarvis.env"
        self.db = root / "vault.sqlite3"
        self.secret = Fernet.generate_key().decode()
        self.env.write_text(
            "ESN_VAULT_KEY=" + self.secret + "\n"
            "ESN_DB_PATH=" + str(self.db) + "\n"
            "ESN_OWNER_TOKEN=this-owner-secret-is-not-output\n"
            "PTERO_API_KEY=ptla_old-revoked-token\n"
            "PTERO_BASE_URL=https://panel.esnoffical.com\n"
        )
        self.env.chmod(0o600)
        c = patch.multiple(connections, DB_PATH=str(self.db), VAULT_KEY=self.secret)
        c.start()
        self.addCleanup(c.stop)
        self.bot_id = connections.save_connection(
            "pterodactyl", "ESN Jarvis Customer Capacity", "", KEY
        )
        b = patch.object(vaultsync.os, "geteuid", return_value=0)
        b.start()
        self.addCleanup(b.stop)
        own = patch.object(vaultsync.os, "fchown")
        own.start()
        self.addCleanup(own.stop)

    def test_absolute_script_path_imports_connections_from_other_cwd(self):
        # Replicates the exact Termius invocation that previously raised
        # ModuleNotFoundError when root's cwd was outside the app directory.
        script = Path(vaultsync.__file__).resolve()
        project = script.parent.parent
        with tempfile.TemporaryDirectory() as elsewhere:
            probe = (
                "import runpy,sys; "
                "runpy.run_path(sys.argv[1],run_name='jarvis_vault_probe'); "
                "import connections; print(connections.__file__)"
            )
            result = subprocess.run(
                [sys.executable, "-I", "-c", probe, str(script)],
                cwd=elsewhere, text=True, capture_output=True, timeout=15,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout.strip()).resolve(),
                         (project / "connections.py").resolve())

    def test_saved_key_stays_hidden_and_old_key_is_replaced(self):
        with patch.object(vaultsync, "_verify_panel_key", return_value=True) as api:
            vaultsync.sync(self.env)
        api.assert_called_once_with(KEY)
        text = self.env.read_text()
        self.assertIn("PTERO_API_KEY=" + KEY, text)
        self.assertNotIn("ptla_old-revoked-token", text)
        self.assertIn("ESN_OWNER_TOKEN=this-owner-secret-is-not-output", text)
        self.assertEqual(self.env.stat().st_mode & 0o777, 0o600)

    def test_validation_failure_does_not_overwrite_working_file(self):
        old = self.env.read_bytes()
        with patch.object(vaultsync, "_verify_panel_key", side_effect=RuntimeError("401 Unauthorized")):
            with self.assertRaisesRegex(RuntimeError, "401"):
                vaultsync.sync(self.env)
        self.assertEqual(old, self.env.read_bytes())

    def test_duplicate_named_credentials_fail_closed(self):
        connections.save_connection("pterodactyl", "ESN Jarvis Customer Capacity", "", KEY)
        with self.assertRaisesRegex(RuntimeError, "unique"):
            vaultsync.sync(self.env)
        self.assertIn("ptla_old-revoked-token", self.env.read_text())

    def test_missing_vault_env_does_not_change_file(self):
        old = self.env.read_text()
        self.env.write_text("ESN_DB_PATH=" + str(self.db) + "\n")
        self.env.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, "vault"):
            vaultsync.sync(self.env)

    def test_refuse_public_env_and_symlinks(self):
        self.env.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "0600"):
            vaultsync.sync(self.env)
        self.env.chmod(0o600)
        target = self.env.parent / "symlink"
        target.symlink_to(self.env)
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            vaultsync.sync(target)

    def test_no_prompt_or_shell_execution(self):
        import inspect
        source = inspect.getsource(vaultsync)
        self.assertNotIn("getpass", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("shell=True", source)
        self.assertNotIn("input(", source)

    def test_fixed_official_panel_endpoint_and_no_redirects(self):
        with patch.object(vaultsync, "build_opener") as opener:
            opener.return_value.open.return_value = FakeResponse()
            self.assertTrue(vaultsync._verify_panel_key(KEY))
            request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, vaultsync.PANEL_NODES_URL)
        self.assertEqual(request.get_header("Authorization"), "Bearer " + KEY)

    def test_unauthorized_is_not_saved_and_does_not_expose_key(self):
        unauthorized = HTTPError(vaultsync.PANEL_NODES_URL, 401, "Rejected", {}, None)
        with patch.object(vaultsync, "build_opener") as opener:
            opener.return_value.open.side_effect = unauthorized
            with self.assertRaises(RuntimeError) as error:
                vaultsync._verify_panel_key(KEY)
        self.assertNotIn(KEY, str(error.exception))
        self.assertIn("401", str(error.exception))


if __name__ == "__main__":
    unittest.main()
