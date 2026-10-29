"""Regression tests: uninstall Jarvis files without touching any ESN customer service."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import uninstall_jarvis as u


class JarvisOnlyUninstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.app = root / "opt" / "esn-jarvis"
        self.app.joinpath("app").mkdir(parents=True)
        self.app.joinpath("app", "jarvis.py").write_text("# Jarvis app\n")
        self.app.joinpath("data").mkdir()
        self.app.joinpath("data", "private-vault.sqlite3").write_text("encrypted")
        self.service_dir = root / "etc" / "systemd" / "system"
        self.service_dir.mkdir(parents=True)
        self.web = self.service_dir / "esn-jarvis.service"
        self.discord = self.service_dir / "esn-jarvis-discord.service"
        self.web.write_text("[Service]\nExecStart=/opt/esn-jarvis/venv/bin/python /opt/esn-jarvis/app/jarvis.py\n")
        self.discord.write_text("[Service]\nExecStart=/opt/esn-jarvis/venv/bin/python /opt/esn-jarvis/app/discord_bridge.py\n")
        self.web_budget = self.service_dir / "esn-jarvis.service.d" / "90-esn-budget.conf"
        self.discord_budget = self.service_dir / "esn-jarvis-discord.service.d" / "90-esn-budget.conf"
        for path in (self.web_budget, self.discord_budget):
            path.parent.mkdir(parents=True)
            path.write_text("[Service]\nSlice=esnjarvis.slice\n")
        self.ollama_budget = self.service_dir / "ollama.service.d" / "90-esn-budget.conf"
        self.ollama_budget.parent.mkdir()
        self.ollama_budget.write_text("[Service]\nSlice=esnjarvis.slice\n")
        self.jarvis_slice = self.service_dir / "esnjarvis.slice"
        self.jarvis_slice.write_text("[Slice]\nMemoryMax=8G\n")
        self.wings = self.service_dir / "wings.service"
        self.wings.write_text("[Service]\nExecStart=/usr/local/bin/wings\n")
        self.docker = self.service_dir / "docker.service"
        self.docker.write_text("[Service]\nExecStart=/usr/bin/dockerd\n")
        self.power_command = root / "usr" / "local" / "sbin" / "esnjarvis"
        self.power_command.parent.mkdir(parents=True)
        self.power_command.write_text(
            '#!/bin/sh\nexec /usr/bin/python3 /opt/esn-jarvis/app/scripts/jarvis_power.py "$@"\n'
        )
        self.env = root / "etc" / "esn-jarvis.env"
        self.env.write_text("PTERO_API_KEY=TEST_SECRET_DONT_PRINT\n")
        self.capacity = root / "etc" / "esn-jarvis-customer-capacity.json"
        self.power_state = root / "var" / "lib" / "esn-jarvis-power"
        self.power_state.mkdir(parents=True)
        self.power_state.joinpath("last-off.json").write_text('{"version": 1, "units": []}')
        self.nginx_available = root / "etc" / "nginx" / "sites-available" / "esn-jarvis"
        self.nginx_enabled = root / "etc" / "nginx" / "sites-enabled" / "esn-jarvis"
        self.nginx_enabled.parent.mkdir(parents=True)
        self.nginx_available.parent.mkdir(parents=True)
        self.nginx_available.write_text(
            "server {\n server_name jarvis.esnoffical.com;\n listen 443 ssl;\n}\n"
        )
        self.nginx_enabled.symlink_to(self.nginx_available)
        self.other_site = self.nginx_available.parent / "esn-panel"
        self.other_site.write_text("server { server_name panel.esnoffical.com; }\n")
        self.acme = root / "var" / "www" / "esn-jarvis-acme"
        self.acme.mkdir(parents=True)
        self.acme.joinpath("challenge").write_text("jarvis-acme")
        self.customer_server = root / "var" / "lib" / "pterodactyl" / "volumes" / "customer"
        self.customer_server.mkdir(parents=True)
        self.customer_server.joinpath("world.dat").write_text("customer-world")
        p = [
            patch.object(u, "APP", self.app),
            patch.object(u, "SERVICE_DIR", self.service_dir),
            patch.object(u, "WEB_UNIT", self.web),
            patch.object(u, "DISCORD_UNIT", self.discord),
            patch.object(u, "POWER_COMMAND", self.power_command),
            patch.object(u, "PRIVATE_ENV", self.env),
            patch.object(u, "CAPACITY_CONFIG", self.capacity),
            patch.object(u, "POWER_STATE", self.power_state),
            patch.object(u, "NGINX_AVAILABLE", self.nginx_available),
            patch.object(u, "NGINX_ENABLED", self.nginx_enabled),
            patch.object(u, "NGINX_ACME", self.acme),
            patch.object(u, "BACKUP", self.nginx_available.parent / ".esn-jarvis-uninstall-tmp"),
            patch.object(u, "DEDICATED_BUDGETS", (self.web_budget, self.discord_budget)),
            patch.object(u.os, "geteuid", return_value=0),
        ]
        self.calls = []
        def fake_run(*args):
            self.calls.append(args)
            return ""
        p.append(patch.object(u, "run", side_effect=fake_run))
        for item in p:
            item.start()
            self.addCleanup(item.stop)

    def test_readonly_plan_does_not_delete_anything(self):
        self.assertTrue(u.plan())
        self.assertTrue(self.app.exists())
        self.assertTrue(self.nginx_available.exists())
        self.assertTrue(self.env.exists())
        self.assertTrue(self.wings.exists())
        self.assertEqual(self.calls, [])

    def test_one_command_removes_jarvis_but_not_customer_servers(self):
        u.apply()
        self.assertFalse(self.app.exists())
        self.assertFalse(self.web.exists())
        self.assertFalse(self.discord.exists())
        self.assertFalse(self.env.exists())
        self.assertFalse(self.power_state.exists())
        self.assertFalse(self.power_command.exists())
        self.assertFalse(self.nginx_available.exists())
        self.assertFalse(self.nginx_enabled.exists())
        self.assertFalse(self.acme.exists())
        self.assertTrue(self.customer_server.joinpath("world.dat").exists())
        self.assertEqual(self.customer_server.joinpath("world.dat").read_text(), "customer-world")
        self.assertTrue(self.wings.exists())
        self.assertTrue(self.docker.exists())
        self.assertTrue(self.other_site.exists())
        self.assertTrue(self.ollama_budget.exists())
        self.assertTrue(self.jarvis_slice.exists())
        self.assertEqual(self.calls, [
            ("systemctl", "disable", "--now", "esn-jarvis-discord.service"),
            ("systemctl", "disable", "--now", "esn-jarvis.service"),
            ("nginx", "-t"),
            ("systemctl", "reload", "nginx"),
            ("systemctl", "daemon-reload"),
        ])

    def test_customer_capacity_mode_blocks_uninstall(self):
        self.capacity.write_text('{"version":1}')
        with self.assertRaisesRegex(RuntimeError, "Customer-first RAM"):
            u.apply()
        self.assertTrue(self.app.exists())
        self.assertEqual(self.calls, [])

    def test_power_record_with_customer_boost_blocks_uninstall(self):
        self.power_state.joinpath("last-off.json").write_text(
            json.dumps({"capacity": {"node_id": 1}})
        )
        with self.assertRaisesRegex(RuntimeError, "panel-recovery"):
            u.apply()
        self.assertTrue(self.env.exists())
        self.assertEqual(self.calls, [])

    def test_other_domain_in_nginx_site_refused(self):
        self.nginx_available.write_text(
            "server { server_name jarvis.esnoffical.com; }\n"
            "server_name esnoffical.com;\n"
        )
        with self.assertRaisesRegex(RuntimeError, "another hostname"):
            u.apply()
        self.assertEqual(self.calls, [])

    def test_wrong_systemd_unit_marker_refused(self):
        self.web.write_text("[Service]\nExecStart=/usr/bin/start-other-customer\n")
        with self.assertRaisesRegex(RuntimeError, "Unexpected content"):
            u.apply()
        self.assertTrue(self.customer_server.joinpath("world.dat").exists())
        self.assertEqual(self.calls, [])

    def test_refuse_symlinked_jarvis_tree(self):
        target = self.app.parent / "customer-files"
        target.mkdir()
        target.joinpath("data").write_text("customer")
        import shutil
        shutil.rmtree(self.app)
        self.app.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "symlinked"):
            u.apply()
        self.assertTrue(target.joinpath("data").exists())
        self.assertEqual(self.calls, [])

    def test_reject_nested_customer_mount(self):
        with patch.object(u.os.path, "ismount", side_effect=lambda p: str(p)==str(self.app)):
            with self.assertRaisesRegex(RuntimeError, "ordinary directory"):
                u.apply()
        self.assertTrue(self.customer_server.joinpath("world.dat").exists())
        self.assertEqual(self.calls, [])

    def test_nginx_failure_restores_site_and_stops_deletion(self):
        def fail_reload(*args):
            self.calls.append(args)
            if args == ("systemctl", "reload", "nginx"):
                raise RuntimeError("Test reload failed")
            return ""
        with patch.object(u, "run", side_effect=fail_reload):
            with self.assertRaisesRegex(RuntimeError, "Test reload failed"):
                u.apply()
        self.assertTrue(self.nginx_available.exists())
        self.assertTrue(self.nginx_enabled.is_symlink())
        self.assertTrue(self.app.exists())
        self.assertTrue(self.env.exists())

    def test_requires_root(self):
        with patch.object(u.os, "geteuid", return_value=1001):
            with self.assertRaisesRegex(RuntimeError, "root"):
                u.apply()
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
