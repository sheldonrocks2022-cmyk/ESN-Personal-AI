"""Private Jarvis Command Center route + static navigation checks."""
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import connections
import jarvis


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        owner = patch.object(jarvis, "OWNER_TOKEN", "owner-token-test-abcdefghijklmnopqrstuvwxyz12345")
        owner.start()
        self.addCleanup(owner.stop)
        database = patch.object(connections, "DB_PATH", os.path.join(self.temp.name, "vault.sqlite"))
        database.start()
        self.addCleanup(database.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), jarvis.Handler)
        self.base = "http://127.0.0.1:" + str(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_dashboard_requires_session_and_redirects_to_login(self):
        with urlopen(self.base + "/dashboard", timeout=5) as response:
            self.assertEqual(response.status, 200)  # urllib follows to /connections
            html = response.read()
            self.assertIn(b"Welcome back.", html)
            self.assertNotIn(b"Build bigger.", html)

    def test_authenticated_dashboard_uses_real_endpoint_links(self):
        token = connections.make_session()
        req = Request(self.base + "/dashboard", headers={"Cookie":"esn_session="+token})
        with urlopen(req, timeout=5) as response:
            html = response.read()
            self.assertIn(b"Build bigger.", html)
            self.assertIn(b"/api/operations/resources", html)
            self.assertIn(b"/api/autonomous/plans", html)
            self.assertIn(b"/api/operations/storage", html)
            self.assertIn(b"/assistant", html)
            self.assertIn(b"/studio", html)

    def test_connection_login_route_is_only_one_http_response(self):
        with urlopen(self.base + "/connections", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"Welcome back.", response.read())

    def test_all_pages_share_mobile_navigation(self):
        web = os.path.join(os.path.dirname(jarvis.__file__), "web")
        for name in ("connections", "assistant", "tasks", "studio"):
            with self.subTest(page=name):
                with open(os.path.join(web, name + ".html"), encoding="utf-8") as file:
                    html=file.read()
                self.assertIn('class="jarvis-subnav"',html)
                self.assertIn('href="/dashboard"', html)
                self.assertIn('href="/assistant"', html)
                self.assertIn('href="/tasks"', html)
                self.assertIn('href="/connections"',html)


if __name__ == "__main__":
    unittest.main()
