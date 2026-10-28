import json
import os
import sqlite3
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
from cryptography.fernet import Fernet
import connections
import jarvis


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(connections, 'DB_PATH', os.path.join(self.tmp.name, 'test.sqlite3')),
            patch.object(connections, 'VAULT_KEY', Fernet.generate_key().decode()),
            patch.object(connections, 'PIN_HASH', connections.hash_pin('839172')),
        ]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def test_pin_hash_and_session(self):
        self.assertTrue(connections.verify_pin('839172'))
        self.assertFalse(connections.verify_pin('111111'))
        self.assertNotIn('839172', connections.PIN_HASH)
        session = connections.make_session()
        self.assertTrue(connections.session_valid(session))
        connections.end_session(session)
        self.assertFalse(connections.session_valid(session))

    def test_encrypted_vault_no_secret_in_listing(self):
        value = 'test_secret_not_for_plaintext_storage'
        ident = connections.save_connection('discord_bot', 'My Bot', 'test-user', value)
        self.assertEqual(connections.read_secret_local(ident), value)
        self.assertNotIn(value, str(connections.list_connections()))
        with sqlite3.connect(connections.DB_PATH) as con:
            raw = con.execute('SELECT secret_blob FROM vault_connections').fetchone()[0]
        self.assertNotIn(value.encode(), raw)
        self.assertTrue(connections.delete_connection(ident))
        with self.assertRaises(KeyError): connections.read_secret_local(ident)

    def test_invalid_connection_rejected(self):
        with self.assertRaises(ValueError): connections.save_connection('dangerous', 'No', '', 'secret')
        with self.assertRaises(ValueError): connections.save_connection('website', 'No', '', '')

    def test_rate_limit(self):
        source = 'test-client'
        for _ in range(5): connections.record_attempt(source, False)
        self.assertFalse(connections.source_allowed(source))
        connections.record_attempt(source, True)
        self.assertTrue(connections.source_allowed(source))

    def test_http_login_csrf_and_vault(self):
        token = 'this-is-a-fake-owner-token-for-tests-123456'
        with patch.object(jarvis, 'OWNER_TOKEN', token), patch.dict(os.environ, {'ESN_OWNER_TOKEN': token}):
            server = ThreadingHTTPServer(('127.0.0.1', 0), jarvis.Handler)
            host = 'http://127.0.0.1:' + str(server.server_port)
            with patch.object(connections, 'PUBLIC_ORIGIN', host), patch.object(connections, 'COOKIE_SECURE', False):
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    def request(path, body=None, cookie=None, csrf=None, origin=True, method=None):
                        headers = {'Content-Type': 'application/json'}
                        if origin: headers['Origin'] = host
                        if cookie: headers['Cookie'] = cookie
                        if csrf: headers['X-ESN-CSRF'] = csrf
                        req = Request(host+path, data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
                        try:
                            with urlopen(req, timeout=3) as r:
                                return r.status, json.loads(r.read()), r.headers.get('Set-Cookie', '')
                        except HTTPError as e:
                            return e.code, json.loads(e.read()), ''
                    self.assertEqual(request('/api/connections')[0], 401)
                    self.assertEqual(request('/api/connections/login', {'pin':'839172','owner_token':'bad'})[0], 401)
                    self.assertEqual(request('/api/connections/login', {'pin':'839172','owner_token':token}, origin=False)[0], 403)
                    code, body, ck = request('/api/connections/login', {'pin':'839172','owner_token':token})
                    self.assertEqual(code, 200)
                    cookie = ck.split(';', 1)[0]
                    self.assertEqual(request('/api/connections', cookie=cookie)[0], 200)
                    payload={'kind':'discord_bot', 'label':'Test Discord', 'login':'bot', 'secret':'testtoken-super-secret'}
                    self.assertEqual(request('/api/connections', payload, cookie=cookie)[0], 403)
                    self.assertEqual(request('/api/connections', payload, cookie=cookie, csrf=body['csrf'])[0], 201)
                    listing=request('/api/connections', cookie=cookie)[1]
                    self.assertEqual(listing['items'][0]['label'], 'Test Discord')
                    self.assertNotIn('testtoken-super-secret', str(listing))
                    self.assertEqual(request('/api/connections/logout', {},cookie=cookie,csrf=body['csrf'])[0],200)
                    self.assertEqual(request('/api/connections',cookie=cookie)[0],401)
                finally:
                    server.shutdown(); server.server_close();thread.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
