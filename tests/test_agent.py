import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import os
import tempfile
import unittest
from unittest.mock import patch
import agent
import jarvis


class ToolAgentTests(unittest.TestCase):
    def test_only_allowed_tools_can_be_queued(self):
        calls=[]
        def queue(kind,opts):
            calls.append((kind,opts)); return 'test-job-0001'
        message={'tool_calls':[{'type':'function','function':{'name':'queue_esn_check','arguments':'{"kind":"nodes_snapshot"}'}}]}
        r=agent.respond_to_tool_calls(message,enqueue=queue)
        self.assertEqual(calls,[('nodes_snapshot',{})]); self.assertIn('test-job-0001',r)
        self.assertIn('not finished',r)

    def test_invalid_or_destructive_tools_cannot_execute(self):
        calls=[]
        def queue(kind,opts):
            calls.append((kind,opts)); return 'id'
        samples=[
            {'type':'function','function':{'name':'run_shell','arguments':'{"command":"rm -rf /"}'}},
            {'type':'function','function':{'name':'queue_esn_check','arguments':'{"kind":"delete_customer_server"}'}},
            {'type':'function','function':{'name':'queue_esn_check','arguments':'{"kind":"panel_health","command":"sudo reboot"}'}},
            {'type':'function','function':{'name':'queue_esn_check','arguments':'{"kind":"browser_scan","target":"http://localhost"}'}},
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                with patch.object(agent.operations,'enqueue',side_effect=ValueError('not allowed')):
                    message={'tool_calls':[sample]}
                    result=agent.respond_to_tool_calls(message,enqueue=lambda k,o: agent.operations.enqueue(k,o))
                    self.assertIn('Rejected',result)
        self.assertEqual(calls,[])

    def test_secrets_are_not_sent_in_prompt(self):
        for val in ['ptla_thisisnotarealtoken12345','sk-testtoken123456789012345','ghp_somethinglong123456']:
            with self.subTest(token=val),self.assertRaises(ValueError):agent.sanitize_message('Here is '+val)
        self.assertEqual(agent.sanitize_message('Check ESN nodes'), 'Check ESN nodes')

    def test_model_response_has_real_job_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(jarvis, 'DB_PATH', os.path.join(tmp,'memory.sqlite')):
                with patch.object(jarvis,'AI_KEY','dummy-not-real'), patch.object(agent.operations,'enqueue',return_value='id-abc') as queue:
                    answer={'choices':[{'message':{'tool_calls':[{'type':'function','function':{'name':'queue_esn_check','arguments':'{"kind":"panel_health"}'}}]}}]}
                    with patch.object(jarvis,'fetch_json',return_value=(200,json.dumps(answer))):
                        reply=jarvis.chat('Check the panel')
                self.assertIn('id-abc',reply)
                self.assertIn('not finished',reply)
                queue.assert_called_once_with('panel_health',{})
                self.assertEqual(len(jarvis.history(10)),2)

    def test_assistant_page_is_owner_gated(self):
        owner='fake-owner-access-token-for-testing-123456789012345'
        with patch.object(jarvis,'OWNER_TOKEN',owner):
            server=ThreadingHTTPServer(('127.0.0.1',0),jarvis.Handler)
            base='http://127.0.0.1:'+str(server.server_port)
            t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
            try:
                with self.assertRaises(HTTPError) as ex:
                    urlopen(base+'/assistant',timeout=5)
                self.assertEqual(ex.exception.code,401)
                req=Request(base+'/assistant',headers={'Authorization':'Bearer '+owner})
                with urlopen(req,timeout=5) as resp:
                    self.assertEqual(resp.status,200)
                    self.assertIn(b'Private Assistant',resp.read())
            finally:
                server.shutdown();server.server_close();t.join(timeout=5)

    def test_tool_calls_are_bounded(self):
        call={'type':'function','function':{'name':'queue_esn_check','arguments':'{"kind":"panel_health"}'}}
        with self.assertRaises(ValueError):agent.respond_to_tool_calls({'tool_calls':[call]*4})

if __name__=='__main__':unittest.main()
