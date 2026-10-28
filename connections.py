"""PIN + owner-token protected Connections dashboard and encrypted credential vault.

Only an explicit local vault consumer can decrypt secrets. Never put decrypted values in
HTTP responses, job logs, memory, or model prompts.
"""
import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet, InvalidToken

DB_PATH = os.environ.get('ESN_DB_PATH', 'esn_jarvis.sqlite3')
PIN_HASH = os.environ.get('ESN_DASHBOARD_PIN_HASH', '')
VAULT_KEY = os.environ.get('ESN_VAULT_KEY', '')
PUBLIC_ORIGIN = os.environ.get('ESN_PUBLIC_ORIGIN', 'https://jarvis.esnoffical.com').rstrip('/')
COOKIE_SECURE = os.environ.get('ESN_COOKIE_SECURE', '1') == '1'
SESSION_TTL = 1800
MAX_AUTH_ATTEMPTS = 5
LOCKOUT_SECONDS = 900
KINDS = {'website', 'discord_bot', 'github', 'stripe', 'pterodactyl', 'spaceship', 'search', 'other'}
UI_PATH = Path(__file__).with_name('web') / 'connections.html'


@contextmanager
def db():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('CREATE TABLE IF NOT EXISTS vault_connections (id TEXT PRIMARY KEY, kind TEXT NOT NULL, label TEXT NOT NULL, login TEXT NOT NULL, secret_blob BLOB NOT NULL, created_at TEXT NOT NULL)')
    con.execute('CREATE TABLE IF NOT EXISTS dashboard_sessions (token_hash TEXT PRIMARY KEY, expires INTEGER NOT NULL)')
    con.execute('CREATE TABLE IF NOT EXISTS dashboard_attempts (source TEXT PRIMARY KEY, failures INTEGER NOT NULL, locked_until INTEGER NOT NULL)')
    con.commit()
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def hash_pin(pin, salt=None, rounds=600000):
    if not isinstance(pin, str) or not (len(pin) == 6 and pin.isascii() and pin.isdigit()):
        raise ValueError('PIN must contain exactly six digits')
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac('sha256', pin.encode(), salt, rounds)
    return f'pbkdf2_sha256${rounds}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(derived).decode()}'


def verify_pin(pin, stored=None):
    stored = PIN_HASH if stored is None else stored
    try:
        scheme, rounds, salt, expected = stored.split('$')
        if scheme != 'pbkdf2_sha256' or not 200000 <= int(rounds) <= 1200000:
            return False
        if not isinstance(pin, str) or len(pin) != 6:
            return False
        calculated = hashlib.pbkdf2_hmac('sha256', pin.encode(), base64.urlsafe_b64decode(salt), int(rounds))
        return hmac.compare_digest(calculated, base64.urlsafe_b64decode(expected))
    except (ValueError, TypeError, OverflowError):
        return False


def cipher():
    if not VAULT_KEY:
        raise RuntimeError('ESN_VAULT_KEY not configured')
    try:
        return Fernet(VAULT_KEY.encode('ascii'))
    except (ValueError, TypeError) as exc:
        raise RuntimeError('Invalid ESN_VAULT_KEY; generate a Fernet key') from exc


def validate_configuration():
    if not PIN_HASH or not VAULT_KEY:
        raise RuntimeError('Set ESN_DASHBOARD_PIN_HASH and ESN_VAULT_KEY before starting dashboard')
    if not PUBLIC_ORIGIN.startswith('https://') and not (not COOKIE_SECURE and PUBLIC_ORIGIN.startswith('http://127.0.0.1:')):
        raise RuntimeError('ESN_PUBLIC_ORIGIN must use HTTPS in production')
    cipher()
    if not verify_pin('000000') and not PIN_HASH.startswith('pbkdf2_sha256$'):
        raise RuntimeError('Bad PIN hash format')


def save_connection(kind, label, login, secret):
    if kind not in KINDS or not isinstance(label, str) or not 1 <= len(label.strip()) <= 80:
        raise ValueError('Invalid connection type or label')
    if not isinstance(login, str) or len(login) > 256:
        raise ValueError('Invalid username or account ID')
    if not isinstance(secret, str) or not 1 <= len(secret) <= 8192:
        raise ValueError('Secret must be 1-8192 characters')
    ident = secrets.token_urlsafe(16)
    blob = cipher().encrypt(secret.encode('utf-8'))
    with db() as con:
        con.execute('INSERT INTO vault_connections VALUES (?,?,?,?,?,?)', (ident, kind, label.strip(), login, blob, datetime.now(timezone.utc).isoformat()))
    return ident


def list_connections():
    with db() as con:
        rows = con.execute('SELECT id,kind,label,login,created_at FROM vault_connections ORDER BY created_at DESC').fetchall()
    return [dict(r) for r in rows]


def delete_connection(ident):
    with db() as con:
        cur = con.execute('DELETE FROM vault_connections WHERE id=?', (ident,))
        return cur.rowcount > 0


def read_secret_local(ident):
    """Server-side only; never expose through an HTTP handler or model context."""
    with db() as con:
        row = con.execute('SELECT secret_blob FROM vault_connections WHERE id=?', (ident,)).fetchone()
    if not row:
        raise KeyError('Connection not found')
    try:
        return cipher().decrypt(row['secret_blob']).decode('utf-8')
    except InvalidToken as exc:
        raise RuntimeError('Vault decryption failed (wrong key or corrupted data)') from exc


def discord_bot_identity(ident):
    with db() as con:
        row = con.execute('SELECT kind FROM vault_connections WHERE id=?', (ident,)).fetchone()
    if not row or row['kind'] != 'discord_bot':
        raise ValueError('Select a Discord bot connection')
    token = read_secret_local(ident)
    req = Request('https://discord.com/api/v10/users/@me', headers={'Authorization': 'Bot ' + token, 'User-Agent': 'ESN-Jarvis/0.2'})
    try:
        with urlopen(req, timeout=8) as r:
            obj = json.loads(r.read(65536))
        return {'connected': True, 'bot_id': obj['id'], 'bot_name': obj['username']}
    except (HTTPError, URLError, KeyError, ValueError, TimeoutError):
        return {'connected': False, 'error': 'Unable to validate bot token or reach Discord'}


def make_session():
    token = secrets.token_urlsafe(32)
    with db() as con:
        con.execute('DELETE FROM dashboard_sessions WHERE expires < ?', (int(time.time()),))
        con.execute('INSERT INTO dashboard_sessions VALUES (?,?)', (hashlib.sha256(token.encode()).hexdigest(), int(time.time()) + SESSION_TTL))
    return token


def session_valid(token):
    if not token:
        return False
    digest = hashlib.sha256(token.encode()).hexdigest()
    with db() as con:
        row = con.execute('SELECT expires FROM dashboard_sessions WHERE token_hash=?', (digest,)).fetchone()
    return bool(row and row['expires'] > time.time())


def end_session(token):
    if token:
        with db() as con:
            con.execute('DELETE FROM dashboard_sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))


def source_allowed(source):
    now = int(time.time())
    with db() as con:
        row = con.execute('SELECT failures,locked_until FROM dashboard_attempts WHERE source=?', (source,)).fetchone()
    return not (row and row['locked_until'] > now)


def record_attempt(source, successful):
    with db() as con:
        if successful:
            con.execute('DELETE FROM dashboard_attempts WHERE source=?', (source,))
            return
        row = con.execute('SELECT failures,locked_until FROM dashboard_attempts WHERE source=?', (source,)).fetchone()
        count = (row['failures'] if row else 0) + 1
        con.execute('INSERT OR REPLACE INTO dashboard_attempts VALUES (?,?,?)', (source, count, int(time.time()) + LOCKOUT_SECONDS if count >= MAX_AUTH_ATTEMPTS else 0))


def token_from_cookie(header):
    for part in header.split(';'):
        key, _, value = part.strip().partition('=')
        if key == 'esn_session' and 20 < len(value) < 180:
            return value
    return ''


def csrf_token(token):
    # CSRF key is derived from an independent vault secret, never the PIN.
    return hmac.new(VAULT_KEY.encode(), ('csrf:' + token).encode(), hashlib.sha256).hexdigest()


def handle(handler):
    """Return True if this HTTP request was handled by the connections router."""
    path = handler.path.split('?', 1)[0]
    method = handler.command
    if path not in ('/', '/connections', '/dashboard', '/api/connections', '/api/connections/login', '/api/connections/logout', '/api/connections/test') and not path.startswith('/api/connections/'):
        return False
    if path in ('/', '/connections') and method == 'GET':
        handler.send_html(UI_PATH.read_bytes())
        return True
    token = token_from_cookie(handler.headers.get('Cookie', ''))
    if path == '/dashboard' and method == 'GET':
        if not session_valid(token):
            handler.send_response(302)
            handler.send_header('Location', '/connections')
            handler.send_header('Content-Length', '0')
            handler.send_header('Cache-Control', 'no-store')
            handler.end_headers()
            return True
        handler.send_html((UI_PATH.parent / 'dashboard.html').read_bytes())
        return True
    if path == '/api/connections/login' and method == 'POST':
        if handler.headers.get('Origin', '') != PUBLIC_ORIGIN:
            handler.send_json(403, {'error': 'Request rejected'}); return True
        if not source_allowed('global') or not source_allowed(handler.client_address[0]):
            return handler.send_json(429, {'error': 'Too many attempts. Try again later.'}) or True
        try:
            body = read_json(handler)
        except ValueError:
            handler.send_json(400, {'error': 'Invalid request'}); return True
        pin = body.get('pin', '')
        # Separate owner token is required in addition to the six-digit PIN.
        owner_ok = hmac.compare_digest(str(body.get('owner_token', '')), os.environ.get('ESN_OWNER_TOKEN', ''))
        valid = owner_ok and bool(os.environ.get('ESN_OWNER_TOKEN')) and verify_pin(pin)
        record_attempt(handler.client_address[0], valid)
        record_attempt('global', valid)
        if not valid:
            handler.send_json(401, {'error': 'Invalid credentials'}); return True
        token = make_session()
        handler.send_json(200, {'ok': True, 'csrf': csrf_token(token)}, cookie=cookie_header(token))
        return True
    if not session_valid(token):
        handler.send_json(401, {'error': 'Please sign in'}); return True
    if method in ('POST', 'DELETE'):
        if handler.headers.get('Origin', '') != PUBLIC_ORIGIN or not hmac.compare_digest(handler.headers.get('X-ESN-CSRF', ''), csrf_token(token)):
            handler.send_json(403, {'error': 'Request rejected'}); return True
    if path == '/api/connections' and method == 'GET':
        handler.send_json(200, {'items': list_connections(), 'csrf': csrf_token(token)}); return True
    if path == '/api/connections' and method == 'POST':
        try:
            body = read_json(handler)
            ident = save_connection(body.get('kind'), body.get('label'), body.get('login', ''), body.get('secret'))
        except (ValueError, TypeError, AttributeError) as exc:
            handler.send_json(400, {'error': str(exc)}); return True
        handler.send_json(201, {'id': ident, 'saved': True}); return True
    if path == '/api/connections/test' and method == 'POST':
        try:
            body = read_json(handler)
            result = discord_bot_identity(body.get('id', ''))
        except (ValueError, TypeError, AttributeError) as exc:
            handler.send_json(400, {'error': str(exc)}); return True
        handler.send_json(200, result); return True
    if path == '/api/connections/logout' and method == 'POST':
        end_session(token)
        handler.send_json(200, {'ok': True}, cookie=cookie_header('', delete=True)); return True
    if path.startswith('/api/connections/') and method == 'DELETE':
        ident = path.removeprefix('/api/connections/')
        if len(ident) > 100:
            handler.send_json(400, {'error': 'Invalid connection'}); return True
        removed = delete_connection(ident)
        handler.send_json(200 if removed else 404, {'deleted': removed})
        return True
    handler.send_json(404, {'error': 'Not found'}); return True


def cookie_header(token, delete=False):
    flags = '; HttpOnly; SameSite=Strict; Path=/' + ('; Secure' if COOKIE_SECURE else '')
    if delete:
        return 'esn_session=; Max-Age=0' + flags
    return 'esn_session=' + token + '; Max-Age=1800' + flags


def read_json(handler):
    size = int(handler.headers.get('Content-Length', '0'))
    if not 1 <= size <= 12000:
        raise ValueError('Invalid request size')
    obj = json.loads(handler.rfile.read(size))
    if not isinstance(obj, dict):
        raise ValueError('Expected object')
    return obj


def cli():
    import sys
    if len(sys.argv) < 2 or sys.argv[1] not in ('hash-pin', 'generate-key'):
        raise SystemExit('Usage: python3 -m connections hash-pin | generate-key')
    if sys.argv[1] == 'generate-key':
        print('ESN_VAULT_KEY=' + Fernet.generate_key().decode())
        return
    pin = getpass.getpass('Enter desired 6-digit PIN: ')
    confirm = getpass.getpass('Confirm PIN: ')
    if pin != confirm:
        raise SystemExit('PIN confirmation does not match')
    print('ESN_DASHBOARD_PIN_HASH=' + hash_pin(pin))


if __name__ == '__main__':
    cli()
