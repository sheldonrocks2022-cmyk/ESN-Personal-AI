import json
import os
import tempfile
import unittest
from unittest.mock import patch

import agent
import jarvis
import operations


class PanelJobRoutingTests(unittest.TestCase):
    def test_plain_language_panel_job_is_queued_reliably(self):
        calls = []
        def enqueue(kind, options):
            calls.append((kind, options))
            return 'sample-job-123'
        reply = agent.queue_explicit_panel_job(
            'Check the ESN Hosting panel using your tools. Create a real health-check job and give me its job ID. Do not pretend the task is complete.',
            enqueue=enqueue,
        )
        self.assertEqual(calls, [('panel_health', {})])
        self.assertIn('sample-job-123', reply)
        self.assertIn('not finished', reply)

    def test_questions_and_mixed_requests_do_not_queue_automatically(self):
        for question in (
            'What is the hosting panel?',
            'Redesign the panel',
            'Check the nodes and panel and give me a job ID',
            'Check browser status of panel; create job ID',
        ):
            with self.subTest(question=question):
                with patch.object(agent.operations, 'enqueue') as queue:
                    self.assertIsNone(agent.queue_explicit_panel_job(question))
                    queue.assert_not_called()

    def test_redundant_safe_target_from_small_model(self):
        calls = []
        model = {'tool_calls': [{'type': 'function', 'function': {
            'name': 'queue_esn_check',
            'arguments': {'kind': 'panel_health', 'target': 'panel'},
        }}]}
        reply = agent.respond_to_tool_calls(model, enqueue=lambda k,o: calls.append((k,o)) or 'job-456')
        self.assertEqual(calls, [('panel_health', {})])
        self.assertIn('job-456',reply)

    def test_unsafe_or_incorrect_target_is_rejected(self):
        for args in (
            {'kind':'panel_health','target':'website'},
            {'kind':'nodes_snapshot','target':'panel'},
            {'kind':'browser_scan','target':'http://127.0.0.1'},
            {'kind':'delete_customer_server'},
        ):
            with self.subTest(args=args):
                calls=[]
                reply=agent.respond_to_tool_calls(
                    {'tool_calls':[{'type':'function','function':{'name':'queue_esn_check','arguments':json.dumps(args)}}]},
                    enqueue=lambda k,o: calls.append((k,o)) or 'job',
                )
                # The invalid browser URL is rejected at operations.validate, not in this stub.
                if args.get('kind') == 'browser_scan':
                    with patch.object(agent.operations, 'enqueue',side_effect=ValueError('invalid target')):
                        reply=agent.respond_to_tool_calls(
                            {'tool_calls':[{'type':'function','function':{'name':'queue_esn_check','arguments':json.dumps(args)}}]},
                            enqueue=agent.operations.enqueue,
                        )
                self.assertIn('Rejected', reply)
                if args.get('kind') != 'browser_scan':
                    self.assertFalse(calls)

    def test_actual_panel_job_writes_database_row_without_calling_model(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(jarvis, 'DB_PATH', os.path.join(temp, 'test.sqlite')):
                with patch.object(jarvis, 'AI_PROVIDER', 'ollama'):
                    with patch.object(jarvis.local_model, 'chat', side_effect=AssertionError('Model should not be required')):
                        reply = jarvis.chat('Check the Pterodactyl panel and create a health-check job ID')
                self.assertIn('job ID', reply)
                self.assertIn('not finished', reply)
                self.assertEqual(len(operations.jobs()), 1)
                self.assertEqual(operations.jobs()[0]['kind'], 'panel_health')
                self.assertEqual(len(jarvis.history()), 2)


if __name__ == '__main__':
    unittest.main()
