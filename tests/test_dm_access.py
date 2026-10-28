"""Step 54: private Discord DM grants and isolation from owner capabilities."""
import os
import tempfile
import unittest
from unittest.mock import patch

import dm_access
import jarvis
import local_model


class DmAccessTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        setting = patch.object(jarvis, "DB_PATH", os.path.join(folder.name, "jarvis.sqlite"))
        setting.start()
        self.addCleanup(setting.stop)
        self.user = "1515077206886453499"

    def test_default_reply_and_unknown_users_are_denied(self):
        self.assertEqual(dm_access.PRIVATE_REPLY, "This bot is private")
        self.assertEqual(dm_access.consume(self.user, now=100), "denied")
        self.assertEqual(dm_access.active_grants(now=100), [])

    def test_grant_expire_and_message_quota(self):
        grant = dm_access.grant(self.user, 5, 2, now=1000)
        self.assertEqual(grant["expires_at"], 1300)
        self.assertEqual(dm_access.consume(self.user, now=1001), "allowed")
        self.assertEqual(dm_access.consume(self.user, now=1002), "cooldown")
        self.assertEqual(dm_access.consume(self.user, now=1008), "allowed")
        self.assertEqual(dm_access.consume(self.user, now=1018), "denied")
        self.assertEqual(dm_access.active_grants(now=1018), [])
        dm_access.grant(self.user, 5, 10, now=2000)
        self.assertEqual(dm_access.consume(self.user, now=2300), "denied")

    def test_restart_persistence_and_regrant(self):
        dm_access.grant(self.user, 15, 3, now=2000)
        self.assertEqual(dm_access.consume(self.user, now=2010), "allowed")
        self.assertEqual(dm_access.active_grants(now=2011)[0]["remaining"], 2)
        dm_access.grant(self.user, 60, 4, now=2012)
        self.assertEqual(dm_access.active_grants(now=2013)[0]["remaining"], 4)
        self.assertEqual(len(dm_access.active_grants(now=2013)), 1)

    def test_revoke_immediately(self):
        dm_access.grant(self.user, 120, 10, now=2000)
        self.assertTrue(dm_access.revoke(self.user))
        self.assertFalse(dm_access.revoke(self.user))
        self.assertEqual(dm_access.consume(self.user, now=2010), "denied")

    def test_duration_quota_and_userid_bounds(self):
        for value in (True, 0, -1, 4, 1441, "60"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                dm_access.grant(self.user, value)
        for value in (True, 0, 31, "10", -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                dm_access.grant(self.user, 60, value)
        for value in (None, "not-a-user", "1", "../123456789012345678"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                dm_access.validate_user_id(value)

    def test_max_active_guest_grants(self):
        for i in range(10):
            dm_access.grant(str(1515077206886453400 + i), 60, now=5000)
        with self.assertRaises(ValueError):
            dm_access.grant("1515077206886453499", 60, now=5001)
        self.assertEqual(len(dm_access.active_grants(now=5001)), 10)

    def test_guest_chat_has_no_tools_owner_memory_or_history(self):
        with patch.object(local_model, "chat", return_value={"content":"Hello there", "tool_calls":[]}) as model:
            reply = dm_access.guest_chat("Hi Jarvis")
        self.assertEqual(reply, "Hello there")
        args = model.call_args.args
        self.assertEqual(args[1], [])  # Never grant tools.
        self.assertEqual([m["role"] for m in args[0]], ["system", "user"])
        self.assertNotIn("OWNER-APPROVED", str(args))
        self.assertNotIn("esn-business", str(args))

    def test_guest_tool_attempt_is_blocked(self):
        with patch.object(local_model, "chat", return_value={
            "content": "Done", "tool_calls": [{"function":{"name":"queue_esn_check"}}],
        }), self.assertRaises(RuntimeError):
            dm_access.guest_chat("Check someone's node")
        with self.assertRaises(ValueError):
            dm_access.guest_chat("x" * 1301)

    def test_guest_does_not_touch_owner_chat_database(self):
        with patch.object(local_model, "chat", return_value={"content":"Okay","tool_calls":[]}):
            dm_access.guest_chat("What's hosting?")
        with jarvis.database() as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
