"""Step 53: real durable task plans with strict owner approval and safe execution."""
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import autonomous
import jarvis
import operations


class AutonomousPlanTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = os.path.join(directory.name, "test.sqlite")
        setting = patch.object(jarvis, "DB_PATH", self.db)
        setting.start()
        self.addCleanup(setting.stop)
        autonomous.STOP.set()

    def test_preview_only_safe_known_targets(self):
        self.assertEqual(
            autonomous.steps_for_goal("Audit ESN Hosting health"),
            ["panel_health", "esn_website_health", "github_repo_health"],
        )
        self.assertEqual(
            autonomous.steps_for_goal("Check the ESN panel and website"),
            ["panel_health", "esn_website_health"],
        )
        self.assertEqual(
            autonomous.steps_for_goal("Check our GitHub, nodes and servers"),
            ["github_repo_health", "nodes_snapshot", "servers_snapshot"],
        )

    def test_unsafe_ambiguous_and_token_requests_are_rejected(self):
        samples = [
            "Delete customer servers and check the ESN website",
            "Change DNS and check panel",
            "Restart our nodes",
            "Install Playwright and run a browser scan",
            "Build me a new website",
            "Check https://google.com",
            "Check the website with sk-testtoken123456789012345",
            "pay a bill and check the hosting panel",
            "Run shell command and verify uptime",
            "Please just do anything",
        ]
        # Arbitrary external URLs must not be treated as checked targets.
        for prompt in samples:
            with self.subTest(prompt=prompt), self.assertRaises(ValueError):
                autonomous.steps_for_goal(prompt)

    def test_never_executes_without_explicit_approval(self):
        ident = autonomous.create("Check ESN panel and website")
        state = autonomous.get(ident)
        self.assertEqual(state["status"], "awaiting_approval")
        self.assertEqual(len(state["steps"]), 2)
        with patch.object(operations, "run_task") as run:
            self.assertFalse(autonomous.tick())
            run.assert_not_called()
        self.assertEqual(autonomous.approve(ident), "running")
        with self.assertRaises(ValueError):
            autonomous.approve(ident)

    def test_real_steps_are_ordered_and_persist_results_after_reopen(self):
        ident = autonomous.create("Check ESN panel, website and GitHub")
        autonomous.approve(ident)
        called = []
        def execute(kind, opts):
            called.append((kind, opts))
            return {"kind": kind, "reachable": True}
        with patch.object(operations, "run_task", side_effect=execute):
            for _ in range(3):
                self.assertTrue(autonomous.tick())
            self.assertFalse(autonomous.tick())
        self.assertEqual(called, [
            ("panel_health", {}),
            ("esn_website_health", {}),
            ("github_repo_health", {}),
        ])
        stored = autonomous.get(ident)
        self.assertEqual(stored["status"], "completed")
        self.assertEqual(stored["completed_steps"], 3)
        self.assertEqual(stored["steps"][2]["result"]["kind"], "github_repo_health")
        self.assertEqual(stored["steps"][0]["attempts"], 1)
        self.assertEqual(autonomous.plans()[0]["id"], ident)

    def test_failure_retry_limit_and_safe_redacted_error(self):
        ident = autonomous.create("Audit hosting")
        autonomous.approve(ident)
        with patch.object(operations, "run_task", side_effect=RuntimeError("Bearer confidential123")) as run:
            self.assertTrue(autonomous.tick())
            self.assertEqual(autonomous.get(ident)["status"], "running")
            self.assertTrue(autonomous.tick())
            self.assertEqual(autonomous.get(ident)["status"], "failed")
            self.assertFalse(autonomous.tick())
            self.assertEqual(run.call_count, 2)
        stored = autonomous.get(ident)
        self.assertNotIn("confidential123", str(stored))
        self.assertEqual(stored["steps"][0]["attempts"], 2)

    def test_cancel_before_approval_and_while_running(self):
        unapproved = autonomous.create("Check the panel")
        self.assertEqual(autonomous.cancel(unapproved), "cancelled")
        with self.assertRaises(ValueError):
            autonomous.approve(unapproved)
        ident = autonomous.create("Check panel website GitHub")
        autonomous.approve(ident)
        def execute(kind, opts):
            autonomous.cancel(ident)
            return {"ok": True}
        with patch.object(operations, "run_task", side_effect=execute) as run:
            self.assertTrue(autonomous.tick())
            self.assertFalse(autonomous.tick())
        self.assertEqual(run.call_count, 1)
        stored = autonomous.get(ident)
        self.assertEqual(stored["status"], "cancelled")
        self.assertEqual(stored["completed_steps"], 0)
        self.assertEqual(stored["steps"][1]["status"], "cancelled")
        self.assertEqual(stored["steps"][2]["status"], "cancelled")

    def test_resume_expired_read_only_step_without_repeating_completed(self):
        ident = autonomous.create("Check panel and website")
        autonomous.approve(ident)
        with patch.object(operations, "run_task", return_value={"reachable": True}):
            self.assertTrue(autonomous.tick())
        with autonomous.conn() as db:
            db.execute(
                "UPDATE autonomous_steps SET status='running',attempts=1,lease_until=? "
                "WHERE plan_id=? AND position=1",
                (int(time.time()) - 5, ident),
            )
        with patch.object(operations, "run_task", return_value={"reachable": True}) as run:
            self.assertTrue(autonomous.tick())
            run.assert_called_once_with("esn_website_health", {})
        self.assertEqual(autonomous.get(ident)["status"], "completed")
        self.assertEqual(autonomous.get(ident)["steps"][1]["attempts"], 2)

    def test_exhausted_lease_marks_failed_not_an_infinite_loop(self):
        ident = autonomous.create("Check panel")
        autonomous.approve(ident)
        with autonomous.conn() as db:
            db.execute(
                "UPDATE autonomous_steps SET status='running',attempts=2,lease_until=? "
                "WHERE plan_id=? AND position=0",
                (int(time.time()) - 5, ident),
            )
        with patch.object(operations, "run_task") as run:
            self.assertFalse(autonomous.tick())
            run.assert_not_called()
        self.assertEqual(autonomous.get(ident)["status"], "failed")

    def test_active_plan_limit_and_invalid_id(self):
        for i in range(autonomous.MAX_ACTIVE):
            autonomous.create("Check panel")
        with self.assertRaises(ValueError):
            autonomous.create("Check panel")
        for action in (autonomous.get, autonomous.cancel, autonomous.approve):
            with self.assertRaises(ValueError):
                action("../bad-identifier")

    def test_claim_executes_one_step_per_tick_not_parallel(self):
        ident = autonomous.create("Check panel website GitHub")
        autonomous.approve(ident)
        first = autonomous._claim()
        self.assertEqual(first["position"], 0)
        self.assertIsNone(autonomous._claim())
        self.assertEqual(autonomous.get(ident)["steps"][0]["status"], "running")


class AutonomousApiTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        dbpatch = patch.object(jarvis, "DB_PATH", os.path.join(folder.name, "api.sqlite"))
        dbpatch.start()
        self.addCleanup(dbpatch.stop)
        self.owner = "test-autonomous-owner-token-123456789012345"
        ownerpatch = patch.object(jarvis, "OWNER_TOKEN", self.owner)
        ownerpatch.start()
        self.addCleanup(ownerpatch.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), jarvis.Handler)
        self.base = "http://127.0.0.1:" + str(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, path, payload=None, owner=False):
        headers = {"Accept": "application/json"}
        if owner:
            headers["Authorization"] = "Bearer " + self.owner
        if payload is not None:
            headers["Content-Type"] = "application/json"
        req = Request(
            self.base + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers,
            method="POST" if payload is not None else "GET",
        )
        with urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read())

    def test_owner_authorization_and_no_approval_bypass(self):
        for path in ("/api/autonomous/plans", "/api/autonomous/create"):
            with self.subTest(path=path), self.assertRaises(HTTPError) as denied:
                self.request(path, {"goal": "Check panel"} if path.endswith("create") else None)
            self.assertEqual(denied.exception.code, 401)
        status, output = self.request(
            "/api/autonomous/create", {"goal": "Check ESN panel and website"}, owner=True
        )
        self.assertEqual(status, 201)
        plan_id = output["plan_id"]
        self.assertEqual(output["status"], "awaiting_approval")
        _, listdata = self.request("/api/autonomous/plans", owner=True)
        self.assertEqual(listdata["plans"][0]["status"], "awaiting_approval")
        with self.assertRaises(HTTPError) as noowner:
            self.request("/api/autonomous/approve", {"id": plan_id})
        self.assertEqual(noowner.exception.code, 401)
        _, approved = self.request("/api/autonomous/approve", {"id": plan_id}, owner=True)
        self.assertEqual(approved["status"], "running")
        _, stopped = self.request("/api/autonomous/cancel", {"id": plan_id}, owner=True)
        self.assertEqual(stopped["status"], "cancelled")
