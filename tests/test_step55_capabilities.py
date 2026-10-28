"""Step 55: bounded work queue, DM commands, and fixed-provider web research."""
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import autonomous
import dm_commands
import jarvis
import operations
import research
import resources
import worker_budget


class WorkerBudgetTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dbpath = os.path.join(td.name, "work.sqlite")
        p = patch.object(jarvis, "DB_PATH", self.dbpath)
        p.start()
        self.addCleanup(p.stop)

    def test_50_is_queue_capacity_not_parallel_processes(self):
        with operations.conn() as db:
            self.assertEqual(worker_budget.snapshot(db)["queued_capacity"], 50)
            self.assertFalse(worker_budget.snapshot(db)["workers_are_processes"])
        for i in range(50):
            operations.enqueue("panel_health")
        with self.assertRaisesRegex(ValueError, "queue is full"):
            operations.enqueue("panel_health")
        with operations.conn() as db:
            data = worker_budget.snapshot(db)
            self.assertEqual(data["occupied_slots"], 50)
            self.assertEqual(data["available_slots"], 0)
            self.assertEqual(data["max_read_only_check_threads"], 2)
        ident = operations.jobs()[0]["id"]
        self.assertEqual(operations.cancel(ident), "cancelled")
        self.assertIsInstance(operations.enqueue("panel_health"), str)

    def test_autonomous_plan_and_ops_share_same_budget(self):
        for i in range(47):
            operations.enqueue("panel_health")
        with self.assertRaisesRegex(ValueError, "queue is full"):
            autonomous.create("Check panel website and GitHub")
        plan_id = autonomous.create("Check panel and website")
        self.assertEqual(autonomous.get(plan_id)["total_steps"], 2)
        with operations.conn() as db:
            self.assertEqual(worker_budget.occupied_slots(db), 49)
        with self.assertRaises(ValueError):
            autonomous.create("Check panel and website")
        self.assertEqual(autonomous.cancel(plan_id), "cancelled")
        with operations.conn() as db:
            self.assertEqual(worker_budget.occupied_slots(db), 47)

    def test_memory_pressure_defers_new_work_without_deleting_queue(self):
        ident = operations.enqueue("panel_health")
        sample = {
            "shared_cap_active": True,
            "used_bytes": 7 * 1024**3 - 128 * 1024**2,
            "throttle_above_bytes": 7 * 1024**3,
        }
        with patch.object(resources, "snapshot", return_value=sample):
            self.assertFalse(worker_budget.may_start())
            self.assertFalse(operations.tick())
        self.assertEqual(operations.jobs()[0]["status"], "queued")
        with patch.object(resources, "snapshot", return_value={
            **sample, "used_bytes": 3 * 1024**3,
        }):
            self.assertTrue(worker_budget.may_start())

    def test_missing_metrics_are_not_a_proof_of_ram_limit(self):
        with patch.object(resources, "snapshot", return_value={
            "shared_cap_active": False, "used_bytes": None,
        }):
            self.assertTrue(worker_budget.may_start())
            with operations.conn() as db:
                self.assertFalse(worker_budget.snapshot(db)["memory_slice_limit_active"])


class DmCommandTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        p = patch.object(jarvis, "DB_PATH", os.path.join(td.name, "dm.sqlite"))
        p.start()
        self.addCleanup(p.stop)

    def test_strict_prefix_and_help(self):
        self.assertFalse(dm_commands.is_command("!jarvis"))
        self.assertFalse(dm_commands.is_command("hello"))
        self.assertTrue(dm_commands.is_command("!Jarvis help"))
        self.assertIsNone(dm_commands.handle("hello"))
        self.assertIn("!jarvis grant", dm_commands.handle("!jarvis help"))
        self.assertIn("!jarvis search", dm_commands.handle("!jarvis help"))
        self.assertIn("Unknown command", dm_commands.handle("!jarvis rm -rf /"))

    def test_owner_commands_use_approved_functions(self):
        with patch.object(jarvis, "run_panel_job", return_value={"http_status": 200}) as service:
            self.assertIn("200", dm_commands.handle("!jarvis status"))
            service.assert_called_once_with("panel_health")
        with patch.object(research, "search", return_value={"results": []}) as search:
            self.assertEqual(dm_commands.handle("!jarvis search node setup"), "Search returned no web results.")
            search.assert_called_once_with("node setup")
        with patch.object(jarvis, "chat", return_value="Jarvis speaking") as chat:
            self.assertEqual(dm_commands.handle("!jarvis ask What is ESN?"), "Jarvis speaking")
            chat.assert_called_once_with("What is ESN?")

    def test_cancel_and_approve_require_real_plan_id(self):
        response = dm_commands.handle("!jarvis auto Check panel and website")
        self.assertIn("Approval needed", response)
        plans = autonomous.plans()
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["status"], "awaiting_approval")
        self.assertIn("approved", dm_commands.handle("!jarvis approve " + plans[0]["id"]))
        self.assertIn("running", dm_commands.handle("!jarvis plan " + plans[0]["id"]))
        self.assertIn("cancelled", dm_commands.handle("!jarvis cancel " + plans[0]["id"]))

    def test_guest_scopes_are_not_in_text_commands(self):
        # Module intentionally contains only owner operations. Discord listener
        # applies its owner ID condition before dispatching.
        with open(dm_commands.__file__, encoding="utf-8") as file:
            text = file.read()
        self.assertNotIn("read_secret_local", text)
        self.assertNotIn("subprocess", text)


class WebSearchTests(unittest.TestCase):
    def test_needs_explicit_credential(self):
        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "",
                                     "BRAVE_SEARCH_CONNECTION_ID": ""}):
            with self.assertRaises(RuntimeError):
                research.search("ESN hosting")
        with self.assertRaises(ValueError):
            research.search("x")

    def test_only_fixed_provider_url_and_safe_results(self):
        body = {"web":{"results":[
            {"title":"Helpful hosting guide","description":"Set up a server safely.",
             "url":"https://example.org/setup"},
            {"title":"Unsafe scheme","url":"http://insecure.example/"},
            {"title":"Remote shell","url":"javascript:alert(1)"},
        ]}}
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self,*args): return json.dumps(body).encode()
        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "fake-for-unit-tests",
                                     "BRAVE_SEARCH_CONNECTION_ID": ""}), \
             patch.object(research, "urlopen", return_value=Response()) as api:
            result = research.search("How to host a Discord bot?")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["url"], "https://example.org/setup")
        req = api.call_args.args[0]
        self.assertEqual(req.full_url.split("?")[0], "https://api.search.brave.com/res/v1/web/search")
        self.assertEqual(req.get_header("X-subscription-token"), "fake-for-unit-tests")
        self.assertNotIn("fake-for-unit-tests", str(result))
        self.assertIn("not independently verified", research.format_results(result))


if __name__ == "__main__":
    unittest.main()
