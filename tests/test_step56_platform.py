"""Step 56: scoped bot identities, owner sends, search REST API and CPU model routing."""
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from cryptography.fernet import Fernet
import agent
import connections
import jarvis
import local_model
import managed_bots
import research
import research_api
import resources


class FakeResponse:
    def __init__(self, payload):
        self.raw = json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, limit=65536): return self.raw[:limit]


class SetupVault(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = tmp.name
        p = patch.multiple(
            connections, DB_PATH=os.path.join(folder, "vault.sqlite"),
            VAULT_KEY=Fernet.generate_key().decode())
        p.start()
        self.addCleanup(p.stop)
        self.ident = connections.save_connection(
            "discord_bot", "ESN Test bot", "", "PRIVATE_FAKE_BOT_TOKEN_1234"
        )
        self.channel_id = "1515077206886453469"
        self.guild_id = "1515077206886453468"


class ManagedBotTests(SetupVault):
    def test_only_managed_bot_vault_kind_can_authenticate(self):
        others = connections.save_connection("website", "Unrelated account", "", "PRIVATE_WEB_SECRET")
        self.assertEqual(managed_bots.list_bots(), [{"id": self.ident, "label": "ESN Test bot"}])
        with self.assertRaises(ValueError):
            managed_bots.identity(others)
        with self.assertRaises(ValueError):
            managed_bots.channel_preview("../bad", self.channel_id)

    def test_verified_identity_does_not_echo_token(self):
        with patch.object(managed_bots, "_discord_request", return_value={
            "bot": True, "id": "1564901565813493841", "username": "ESN Guardian"}) as remote:
            result = managed_bots.identity(self.ident)
        self.assertEqual(result["bot_name"], "ESN Guardian")
        self.assertEqual(remote.call_args.args[0], "/users/@me")
        self.assertEqual(remote.call_args.args[1], "PRIVATE_FAKE_BOT_TOKEN_1234")
        self.assertNotIn("PRIVATE_FAKE_BOT_TOKEN_1234", str(result))

    def test_bot_guild_message_requires_channel_preflight_and_confirmation(self):
        calls = []
        def remote(path, token, payload=None):
            calls.append((path, token, payload))
            if path.endswith("/messages"):
                return {"id": "1564901565813493999"}
            return {"id": self.channel_id, "type": 0, "guild_id": self.guild_id, "name": "general"}
        with patch.object(managed_bots, "_discord_request", side_effect=remote):
            with self.assertRaises(ValueError):
                managed_bots.send_one(self.ident, self.channel_id, "Hello", confirm=False)
            data = managed_bots.send_one(self.ident, self.channel_id, "Hi from ESN", confirm=True)
            self.assertEqual(data["message_id"], "1564901565813493999")
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[1][2]["allowed_mentions"], {"parse": []})
            self.assertEqual(calls[1][2]["content"], "Hi from ESN")
            with self.assertRaisesRegex(ValueError, "cooldown"):
                managed_bots.send_one(self.ident, self.channel_id, "Again", confirm=True)

    def test_never_sends_to_dm_or_unlisted_guild_or_mentions(self):
        with patch.object(managed_bots, "_discord_request", return_value={
            "id": self.channel_id, "type": 1, "name": "private"}):
            with self.assertRaises(ValueError):
                managed_bots.channel_preview(self.ident, self.channel_id)
        with patch.dict(os.environ, {"ESN_MANAGED_GUILD_IDS": "1515077206886453490"}), \
             patch.object(managed_bots, "_discord_request", return_value={
                "id": self.channel_id, "type": 0, "guild_id": self.guild_id,
                "name": "general"}):
            with self.assertRaises(ValueError):
                managed_bots.channel_preview(self.ident, self.channel_id)
        with self.assertRaises(ValueError):
            managed_bots.send_one(self.ident, self.channel_id, "@everyone urgent", confirm=True)
        with self.assertRaises(ValueError):
            managed_bots.channel_preview(self.ident, "https://example.org")

    def test_http_api_forbids_untrusted_discord_api_redirects(self):
        class Redirect:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, *args): return b'{}'
        with patch.object(managed_bots, "build_opener") as opener:
            opener.return_value.open.return_value = Redirect()
            managed_bots._discord_request("/users/@me", "MY_FAKE_TEST_TOKEN")
            req = opener.return_value.open.call_args.args[0]
            self.assertEqual(req.full_url, "https://discord.com/api/v10/users/@me")
            self.assertEqual(req.get_header("Authorization"), "Bot MY_FAKE_TEST_TOKEN")
        with self.assertRaises(ValueError):
            managed_bots._discord_request("https://untrusted.example", "not_real")


class ResearchTests(SetupVault):
    def test_local_searxng_uses_only_loopback_and_strips_unsafe_links(self):
        payload = {"results": [
            {"url": "https://searxng.org/", "title": "SearXNG", "content": "Open source search"},
            {"url": "http://private.local", "title": "Ignore", "content": "Ignore"}
        ]}
        with patch.dict(os.environ, {"JARVIS_SEARCH_BACKEND": "searxng"}), \
             patch.object(research, "urlopen", return_value=FakeResponse(payload)) as fake:
            data = research.search("coding tutorials")
        req = fake.call_args.args[0]
        self.assertTrue(req.full_url.startswith("http://127.0.0.1:8888/search?"))
        self.assertEqual(data["provider"], "Jarvis local SearXNG")
        self.assertEqual(len(data["results"]), 1)

    def test_brave_search_uses_encrypted_vault_automatically(self):
        key = "BRAVE_KEY_ONLY_IN_VAULT"
        connections.save_connection("search", "Brave Search", "", key)
        payload = {"web": {"results": [{"url": "https://example.org", "title": "Useful", "description": "Result"}]}}
        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "",
                                     "BRAVE_SEARCH_CONNECTION_ID": "",
                                     "JARVIS_SEARCH_BACKEND": "brave"}), \
             patch.object(research, "urlopen", return_value=FakeResponse(payload)) as fake:
            self.assertTrue(research.enabled())
            data = research.search("ESN Jarvis documentation")
        request = fake.call_args.args[0]
        self.assertEqual(request.get_header("X-subscription-token"), key)
        self.assertNotIn(key, str(data))

    def test_explicit_owner_search_does_not_autogenerate_private_model_queries(self):
        with patch.object(research, "search", return_value={
            "results": [{"url": "https://example.org", "title": "Docs", "snippet": "Hello"}]
        }) as search:
            self.assertIn("Docs", agent.explicit_web_search("Search the web for Pterodactyl API docs"))
            search.assert_called_once_with("Pterodactyl API docs")
        self.assertIsNone(agent.explicit_web_search("How are my accounts configured?"))

    def test_guest_uses_only_fast_model_in_adaptive_mode(self):
        env={"ESN_AI_PROFILE": "adaptive", "OLLAMA_MODEL": "qwen3:1.7b",
             "OLLAMA_MODEL_QUALITY": "qwen3:4b"}
        with patch.dict(os.environ, env), \
             patch.object(resources, "snapshot", return_value={
                "shared_cap_active": True, "used_bytes": 1024**3,
                "throttle_above_bytes": 7 * 1024**3}), \
             patch.object(local_model, "_installed", return_value=True):
            messages = [{"role": "user", "content": "Debug Python programming and reason about algorithms"}]
            self.assertEqual(local_model._select_model(messages, []), "qwen3:1.7b")
            self.assertEqual(local_model._select_model(messages, [{"type": "function"}]), "qwen3:4b")

    def test_quality_downgrades_when_ram_limit_not_verified(self):
        env={"ESN_AI_PROFILE": "quality", "OLLAMA_MODEL": "qwen3:1.7b",
             "OLLAMA_MODEL_QUALITY": "qwen3:4b"}
        with patch.dict(os.environ, env), \
             patch.object(resources, "snapshot", return_value={
                "shared_cap_active": False, "used_bytes": None,
            }):
            self.assertEqual(local_model._select_model(
                [{"role": "user", "content": "Write a Python program"}], [{"type": "function"}]
            ), "qwen3:1.7b")


class NewAPITests(SetupVault):
    def setUp(self):
        super().setUp()
        server_token = "original-jarvis-owner-token-for-tests-1234567890"
        scope_token = "dedicated-search-api-key-for-tests-1234567890"
        env = patch.dict(os.environ, {"ESN_SEARCH_API_TOKEN": scope_token,
                                      "JARVIS_SEARCH_BACKEND": "brave"})
        env.start()
        self.addCleanup(env.stop)
        p = patch.object(jarvis, "OWNER_TOKEN", server_token)
        p.start()
        self.addCleanup(p.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), jarvis.Handler)
        self.base = "http://127.0.0.1:" + str(self.server.server_port)
        origin = patch.object(connections, "PUBLIC_ORIGIN", self.base)
        origin.start()
        self.addCleanup(origin.stop)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._close_server)
        self.owner_cookie = "esn_session=" + connections.make_session()
        self.csrf = connections.csrf_token(self.owner_cookie.split("=", 1)[1])
        self.scoped_key = scope_token

    def _close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, path, payload=None, headers=None):
        hdr = {"Accept": "application/json"}
        if headers: hdr.update(headers)
        if payload is not None: hdr["Content-Type"] = "application/json"
        request = Request(self.base + path, headers=hdr,
                          method="POST" if payload is not None else "GET",
                          data=json.dumps(payload).encode() if payload is not None else None)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_search_only_key_cannot_touch_connection_or_bots(self):
        token = {"Authorization": "Bearer " + self.scoped_key}
        self.assertEqual(self.request("/api/bots", headers=token)[0], 401)
        self.assertEqual(self.request("/api/connections", headers=token)[0], 401)
        self.assertEqual(self.request("/api/search/status", headers=token)[0], 200)
        with patch.object(research, "search", return_value={
            "provider": "test", "query": "hosting", "results": []
        }):
            status, result = self.request("/api/search", {"query": "hosting"}, headers=token)
        self.assertEqual(status, 200)
        self.assertEqual(result["provider"], "test")

    def test_owner_cookie_and_csrf_required_for_search(self):
        cookie = {"Cookie": self.owner_cookie}
        self.assertEqual(self.request("/api/search", {"query": "test"}, headers=cookie)[0], 403)
        cookie.update({"X-ESN-CSRF": self.csrf, "Origin": self.base})
        with patch.object(research, "search", return_value={
            "provider": "test", "query": "hosting", "results": []
        }):
            self.assertEqual(self.request("/api/search", {"query": "hosting"}, headers=cookie)[0], 200)
        self.assertEqual(self.request("/api/search", {"query": "hosting", "url": "evil"}, headers=cookie)[0], 400)

    def test_discord_bot_api_requires_owner_and_csrf(self):
        self.assertEqual(self.request("/api/bots")[0], 401)
        self.assertEqual(self.request("/api/bots/send", {
            "connection_id": self.ident, "channel_id": self.channel_id,
            "content": "hello", "confirm": True
        })[0], 401)
        cookie = {"Cookie": self.owner_cookie}
        status, bots = self.request("/api/bots", headers=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(bots["bots"][0]["label"], "ESN Test bot")
        self.assertNotIn("PRIVATE_FAKE_BOT_TOKEN_1234", str(bots))
        self.assertEqual(self.request("/api/bots/identity", {"connection_id": self.ident},
                                      headers=cookie)[0], 403)

    def test_search_scope_is_not_master_auth(self):
        token = {"Authorization": "Bearer " + self.scoped_key}
        self.assertEqual(self.request("/api/operations", headers=token)[0], 401)
        self.assertEqual(self.request("/api/assistant/chat", {"message":"hello"}, headers=token)[0], 401)


if __name__ == "__main__":
    unittest.main()
