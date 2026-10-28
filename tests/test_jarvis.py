import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import jarvis

class JarvisTests(unittest.TestCase):
    def test_job_allowlist(self):
        self.assertEqual(jarvis.ALLOWED_JOBS, {"panel_health", "nodes_snapshot", "servers_snapshot"})
        with self.assertRaises(ValueError):
            jarvis.submit_job("delete_customer_server")

    def test_origin_validation(self):
        self.assertEqual(jarvis.clean_panel_url("https://panel.esnoffical.com/"), "https://panel.esnoffical.com")
        for url in ("http://panel.esnoffical.com", "https://admin:pass@panel.esnoffical.com", "https://panel.esnoffical.com/other", "https://panel.esnoffical.com?key=foo"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                jarvis.clean_panel_url(url)

    def test_database_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(jarvis, "DB_PATH", os.path.join(tmp, "db.sqlite3")):
                with jarvis.database() as conn:
                    conn.execute("INSERT INTO messages (role,content,created_at) VALUES (?,?,?)", ("user", "hello", jarvis.utc_now()))
                self.assertEqual(jarvis.history()[0]["content"], "hello")

    def test_read_only_node_projection(self):
        payload = '{"data":[{"attributes":{"id":2,"name":"Node 2","maintenance_mode":false,"fqdn":"secret"}}],"meta":{"pagination":{"current_page":1,"total_pages":1}}}'
        with patch.object(jarvis, "PTERO_KEY", "test-key"), patch.object(jarvis, "fetch_json", return_value=(200, payload)) as fake:
            result = jarvis.run_panel_job("nodes_snapshot")
        self.assertEqual(result["items"], [{"id": 2, "name": "Node 2", "maintenance_mode": False}])
        self.assertNotIn("secret", str(result))
        self.assertTrue(fake.call_args.kwargs["bearer"] == "test-key")

if __name__ == "__main__":
    unittest.main()
