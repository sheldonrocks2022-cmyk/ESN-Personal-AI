import io
import json
import unittest
from unittest.mock import patch
import local_model
import jarvis
import agent
import tempfile
import os


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self, n): return self.payload[:n]


class LocalModelTests(unittest.TestCase):
    def test_plain_chat_stays_on_loopback(self):
        result = {"message":{"content":"Hello from local Jarvis"}}
        def fake(req, timeout):
            self.assertEqual(req.full_url,"http://127.0.0.1:11434/api/chat")
            self.assertEqual(timeout,120)
            request=json.loads(req.data)
            self.assertFalse(request["stream"])
            self.assertEqual(request["keep_alive"],0)
            self.assertEqual(request["options"]["num_ctx"],4096)
            return FakeResponse(result)
        with patch.object(local_model,"urlopen",side_effect=fake):
            answer=local_model.chat([{"role":"user","content":"hello"}],[])
        self.assertEqual(answer["content"],"Hello from local Jarvis")

    def test_ollama_tool_arguments_are_normalized(self):
        raw={"message":{"content":"","tool_calls":[{"function":{"name":"queue_esn_check","arguments":{"kind":"panel_health"}}}]}}
        with patch.object(local_model,"urlopen",return_value=FakeResponse(raw)):
            result=local_model.chat([],agent.TOOLS)
        self.assertEqual(result["tool_calls"][0]["type"],"function")
        self.assertEqual(json.loads(result["tool_calls"][0]["function"]["arguments"]),{"kind":"panel_health"})

    def test_invalid_model_name_is_rejected_before_network(self):
        with patch.dict(os.environ,{"OLLAMA_MODEL":"http://untrusted/test"}):
            with patch.object(local_model,"urlopen") as network:
                with self.assertRaises(RuntimeError):
                    local_model.chat([],[])
                network.assert_not_called()

    def test_local_provider_runs_through_existing_safe_executor(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(jarvis,"AI_PROVIDER","ollama"), patch.object(jarvis,"AI_KEY",""), patch.object(jarvis,"DB_PATH",td+"/memory.sqlite"):
                with patch.object(local_model,"chat",return_value={"content":"Local response","tool_calls":[]}) as call:
                    self.assertEqual(jarvis.chat("Hello local Jarvis"),"Local response")
                    self.assertEqual(len(jarvis.history()),2)
                    call.assert_called_once()

if __name__=="__main__":
    unittest.main()
