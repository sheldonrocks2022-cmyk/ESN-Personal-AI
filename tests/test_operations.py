"""Persistent task engine tests exercise database persistence and real dispatch boundary."""
import os
import tempfile
import time
import unittest
from unittest.mock import patch

import jarvis
import operations


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        p = patch.object(jarvis, 'DB_PATH', os.path.join(self.folder.name, 'test.sqlite'))
        p.start()
        self.addCleanup(p.stop)
        operations.STOP.set()

    def test_strict_allowlist_and_browser_targets(self):
        for bad in ('delete_customer_server', 'shell', 'stripe_refund', None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                operations.enqueue(bad)
        for bad in ('http://127.0.0.1', 'https://google.com', 'http://169.254.169.254'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                operations.enqueue('browser_scan', {'target': bad})
        with self.assertRaises(ValueError):
            operations.enqueue('panel_health', {'url': 'https://example.com'})

    def test_queue_survives_and_result_is_real(self):
        ident = operations.enqueue('nodes_snapshot')
        self.assertEqual(operations.jobs()[0]['status'], 'queued')
        with patch.object(jarvis, 'run_panel_job', return_value={'items': [{'name': 'Test node'}]}) as run:
            self.assertTrue(operations.tick())
        row = next(r for r in operations.jobs() if r['id'] == ident)
        self.assertEqual(row['status'], 'completed')
        self.assertIn('Test node', row['result_json'])
        self.assertEqual(row['attempts'], 1)
        run.assert_called_once_with('nodes_snapshot')
        with operations.conn() as db:
            count = db.execute('SELECT count(*) FROM operation_jobs').fetchone()[0]
        self.assertEqual(count, 1)

    def test_cancel_queued(self):
        ident = operations.enqueue('panel_health')
        self.assertEqual(operations.cancel(ident), 'cancelled')
        self.assertFalse(operations.tick())
        self.assertEqual(operations.jobs()[0]['status'], 'cancelled')

    def test_schedule_creation_pausing_and_due_tick(self):
        with self.assertRaises(ValueError):
            operations.schedule('panel_health', 1)
        ident = operations.schedule('panel_health', 15)
        self.assertTrue(operations.schedules()[0]['enabled'])
        with operations.conn() as db:
            db.execute('UPDATE operation_schedules SET next_due=? WHERE id=?', (int(time.time())-1, ident))
        with patch.object(jarvis, 'run_panel_job', return_value={'reachable': True}):
            self.assertTrue(operations.tick())
        self.assertEqual(operations.jobs()[0]['status'], 'completed')
        self.assertGreater(operations.schedules()[0]['next_due'], time.time())
        operations.pause_schedule(ident)
        self.assertFalse(operations.schedules()[0]['enabled'])

    def test_failure_is_bounded_and_does_not_save_secret(self):
        ident = operations.enqueue('nodes_snapshot')
        with patch.object(jarvis, 'run_panel_job', side_effect=RuntimeError('bad token super-secret')):
            self.assertTrue(operations.tick())
            self.assertTrue(operations.tick())
            self.assertFalse(operations.tick())
        row = operations.jobs()[0]
        self.assertEqual(row['id'], ident)
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['attempts'], 2)
        self.assertNotIn('super-secret', str(row))

    def test_unexpired_running_is_not_stolen(self):
        ident = operations.enqueue('panel_health')
        with operations.conn() as db:
            db.execute('UPDATE operation_jobs SET status=?,lease_until=? WHERE id=?', ('running', int(time.time())+30, ident))
        self.assertFalse(operations.tick())
        with operations.conn() as db:
            db.execute('UPDATE operation_jobs SET lease_until=? WHERE id=?', (int(time.time())-1, ident))
        with patch.object(jarvis, 'run_panel_job', return_value={'reachable': True}):
            self.assertTrue(operations.tick())
        self.assertEqual(operations.jobs()[0]['status'], 'completed')

if __name__ == '__main__':
    unittest.main()
