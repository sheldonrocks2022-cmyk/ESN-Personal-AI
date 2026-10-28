import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import creative

class CreativeQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(creative, 'ROOT', Path(self.tmp.name))
        patcher.start(); self.addCleanup(patcher.stop)

    def test_job_persists_with_plan_until_started(self):
        ident = creative.enqueue('logo', {'brand':'ESN', 'symbol':'shield'})
        with creative.db() as db:
            rec = db.execute('SELECT spec_json,status FROM studio_jobs WHERE id=?',(ident,)).fetchone()
            self.assertEqual(rec['status'], 'queued')
            self.assertIn('ESN', rec['spec_json'])
        self.assertTrue(creative.creative_tick())
        self.assertEqual(creative.get_jobs()[0]['status'],'completed')
        with creative.db() as db:
            rec = db.execute('SELECT spec_json FROM studio_jobs WHERE id=?',(ident,)).fetchone()
            self.assertIsNone(rec['spec_json'])

    def test_recover_interrupted_instead_of_losing_all_work(self):
        ident = creative.enqueue('logo', {'brand':'ESN', 'symbol':'orbit'})
        with creative.db() as db:
            db.execute("UPDATE studio_jobs SET status='running' WHERE id=?", (ident,))
        with patch.object(creative, 'ENABLED', True):
            creative.start_worker()
            creative._CREATIVE_STOP.set()
            creative._CREATIVE_WORKER.join(timeout=4)
        self.assertEqual(creative.get_jobs()[0]['status'],'completed')

if __name__ == '__main__': unittest.main()
