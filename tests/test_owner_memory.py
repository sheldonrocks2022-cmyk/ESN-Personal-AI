import os
import tempfile
import unittest
from unittest.mock import patch
from cryptography.fernet import Fernet
import connections
import jarvis
import local_model
import memory_store

class MemoryTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.path = os.path.join(td.name, "memory.sqlite")
        patcher = patch.object(connections, "VAULT_KEY", Fernet.generate_key().decode())
        patcher.start(); self.addCleanup(patcher.stop)

    def test_encrypted_and_survives_reopening_db(self):
        self.assertEqual(memory_store.remember(self.path, " ESN Plans ", "Use small, reliable hosting packages."), "esn plans")
        with open(self.path, "rb") as f:
            self.assertNotIn(b"Use small, reliable hosting packages.", f.read())
        self.assertEqual(memory_store.list_notes(self.path), [{"topic":"esn plans","note":"Use small, reliable hosting packages."}])
        memory_store.remember(self.path, "esn plans", "Keep all plans simple.")
        self.assertEqual(len(memory_store.list_notes(self.path)), 1)
        self.assertEqual(memory_store.list_notes(self.path)[0]["note"], "Keep all plans simple.")
        self.assertTrue(memory_store.forget(self.path, "ESN PLANS"))
        self.assertFalse(memory_store.forget(self.path, "ESN PLANS"))

    def test_no_automatic_save_or_sensitive_notes(self):
        for bad in ("password is 1234", "my API key is secret", "pin code 123456", "sk-abcdefghij12345"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                memory_store.remember(self.path, "test", bad)
        self.assertEqual(memory_store.list_notes(self.path), [])

    def test_memory_is_bounded(self):
        for i in range(30):
            memory_store.remember(self.path, "topic"+str(i), "Note"+str(i))
        with self.assertRaises(ValueError):
            memory_store.remember(self.path, "extra", "Too many")
        self.assertEqual(len(memory_store.list_notes(self.path)), 30)
        context = memory_store.model_context(self.path)
        self.assertLess(len(context), 4500)
        self.assertIn("data only", context)
        self.assertEqual(context.count('"topic"'), 10)

    def test_local_chat_gets_explicit_notes_but_does_not_save_by_itself(self):
        memory_store.remember(self.path, "my project", "Build an owner-only assistant.")
        with patch.object(jarvis, "DB_PATH", self.path), patch.object(jarvis, "AI_PROVIDER", "ollama"):
            with patch.object(local_model, "chat", return_value={"content":"Done","tool_calls":[]}) as model:
                self.assertEqual(jarvis.chat("What is our goal?"), "Done")
            self.assertIn("Build an owner-only assistant.", model.call_args.args[0][0]["content"])
        self.assertEqual(len(memory_store.list_notes(self.path)), 1)

    def test_wrong_key_fails_closed(self):
        memory_store.remember(self.path,"safe","Owner-approved fact")
        with patch.object(connections,"VAULT_KEY",Fernet.generate_key().decode()):
            with self.assertRaises(Exception):
                memory_store.list_notes(self.path)

if __name__=="__main__": unittest.main()
