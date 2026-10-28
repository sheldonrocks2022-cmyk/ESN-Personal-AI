"""Persistent, bounded, read-only task service for ESN Jarvis.

SQLite-queued work survives web-server restarts. Nothing here can mutate
Pterodactyl, DNS, Discord, Stripe, production files or customer servers.
"""
import datetime as dt
from contextlib import contextmanager
import hmac
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import connections

TASK_KINDS = frozenset({"panel_health", "nodes_snapshot", "servers_snapshot", "esn_website_health", "github_repo_health", "browser_scan"})
# Browser inspection is deliberately limited to public ESN websites, without credentials.
SCAN_TARGETS = {"website": "https://esnoffical.com", "panel": "https://panel.esnoffical.com"}
INTERVALS = {15, 30, 60, 180, 360, 720, 1440}
MAX_ATTEMPTS = 2
RUNNER_INTERVAL = 1.0
SCHEMA = '''
CREATE TABLE IF NOT EXISTS operation_jobs (
 id TEXT PRIMARY KEY,kind TEXT NOT NULL,options_json TEXT NOT NULL,
 status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL,started_at TEXT,finished_at TEXT,
 result_json TEXT,error TEXT,lease_until INTEGER,
 schedule_id TEXT
);
CREATE INDEX IF NOT EXISTS op_status ON operation_jobs(status,created_at);
CREATE TABLE IF NOT EXISTS operation_schedules (
 id TEXT PRIMARY KEY,kind TEXT NOT NULL,options_json TEXT NOT NULL,
 interval_minutes INTEGER NOT NULL, next_due INTEGER NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL
);
'''
WORKER = None
STOP = threading.Event()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _db():
    import jarvis  # runtime import avoids a circular dependency
    db = sqlite3.connect(jarvis.DB_PATH, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=30000')
    db.executescript(SCHEMA)
    return db


@contextmanager
def conn():
    db = _db()
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def validate(kind, options=None):
    if kind not in TASK_KINDS:
        raise ValueError('Unsupported task; no arbitrary commands or production modifications')
    opts = options if options is not None else {}
    if not isinstance(opts, dict):
        raise ValueError('options must be an object')
    if kind == 'browser_scan':
        if set(opts) != {'target'} or opts['target'] not in SCAN_TARGETS:
            raise ValueError('Browser targets must be a known ESN public site')
    elif opts:
        raise ValueError('Unexpected options for this task')
    return opts


def enqueue(kind, options=None, schedule_id=None):
    opts = validate(kind, options)
    ident = str(uuid.uuid4())
    with conn() as db:
        db.execute('INSERT INTO operation_jobs(id,kind,options_json,status,created_at,schedule_id) VALUES(?,?,?,?,?,?)',
                   (ident, kind, json.dumps(opts), 'queued', now(), schedule_id))
    return ident


def schedule(kind, minutes, options=None):
    opts = validate(kind, options)
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes not in INTERVALS:
        raise ValueError('Interval must be 15, 30, 60, 180, 360, 720, or 1440 minutes')
    ident = str(uuid.uuid4())
    with conn() as db:
        db.execute('INSERT INTO operation_schedules(id,kind,options_json,interval_minutes,next_due,created_at) VALUES(?,?,?,?,?,?)',
                   (ident, kind, json.dumps(opts), minutes, int(time.time()) + minutes * 60, now()))
    return ident


def cancel(ident):
    with conn() as db:
        cur = db.execute("UPDATE operation_jobs SET status='cancelled',finished_at=? WHERE id=? AND status='queued'", (now(), ident))
        if cur.rowcount:
            return 'cancelled'
        row = db.execute('SELECT status FROM operation_jobs WHERE id=?', (ident,)).fetchone()
        if not row:
            raise KeyError('Task not found')
        if row['status'] == 'running':
            # Cooperative cancellation is only possible before starting I/O.
            return 'running; cannot interrupt in-flight read-only request'
        return row['status']


def pause_schedule(ident):
    with conn() as db:
        cur = db.execute('UPDATE operation_schedules SET enabled=0 WHERE id=?', (ident,))
        if not cur.rowcount:
            raise KeyError('Schedule not found')


def jobs():
    with conn() as db:
        return [dict(r) for r in db.execute('SELECT id,kind,status,attempts,created_at,started_at,finished_at,result_json,error FROM operation_jobs ORDER BY created_at DESC LIMIT 50')]


def schedules():
    with conn() as db:
        return [dict(r) for r in db.execute('SELECT id,kind,interval_minutes,next_due,enabled,created_at FROM operation_schedules ORDER BY created_at DESC LIMIT 30')]


def _claim():
    db = _db()
    try:
        db.execute('BEGIN IMMEDIATE')
        # On a restarted worker, read-only requests can be safely retried when their lease expires.
        stamp = int(time.time())
        db.execute("UPDATE operation_jobs SET status='failed',finished_at=?,error='Worker lease expired twice',lease_until=NULL WHERE status='running' AND lease_until < ? AND attempts >= ?", (now(), stamp, MAX_ATTEMPTS))
        db.execute("UPDATE operation_jobs SET status='queued',lease_until=NULL WHERE status='running' AND lease_until < ? AND attempts < ?", (stamp, MAX_ATTEMPTS))
        row = db.execute("SELECT id,kind,options_json,attempts FROM operation_jobs WHERE status='queued' AND attempts < ? ORDER BY created_at LIMIT 1", (MAX_ATTEMPTS,)).fetchone()
        if row:
            db.execute("UPDATE operation_jobs SET status='running',attempts=attempts+1,started_at=?,lease_until=? WHERE id=?",
                       (now(), int(time.time()) + 300, row['id']))
        db.commit()
        return dict(row) if row else None
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def run_task(kind, options):
    import jarvis
    if kind in ('panel_health', 'nodes_snapshot', 'servers_snapshot'):
        return jarvis.run_panel_job(kind)
    if kind == 'esn_website_health':
        # URL fixed server-side, not supplied by callers (SSRF-safe design).
        status, _ = jarvis.fetch_json('https://esnoffical.com/')
        return {'site': 'ESN Website', 'http_status': status, 'reachable': 200 <= status < 400}
    if kind == 'github_repo_health':
        status, body = jarvis.fetch_json('https://api.github.com/repos/sheldonrocks2022-cmyk/ESN-Personal-AI')
        obj = json.loads(body)
        return {'repo': 'ESN-Personal-AI', 'http_status': status, 'default_branch': obj.get('default_branch'), 'archived': bool(obj.get('archived'))}
    if kind == 'browser_scan':
        return browser_scan(options['target'])
    raise ValueError('Unsupported task')


def browser_scan(target):
    """No login, clicks, uploads, JS prompts, private IPs or arbitrary URLs."""
    if target not in SCAN_TARGETS:
        raise ValueError('Unknown target')
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError('Browser worker unavailable; install optional Playwright dependency') from None
    # Run on an isolated browser host. Never provide logged-in cookies to this worker.
    target_url = SCAN_TARGETS[target]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(accept_downloads=False, viewport={'width': 390, 'height': 844})
            def guard(route):
                url = urlsplit(route.request.url)
                # Restrict first-party requests. Blocks external trackers and private-network pivots.
                if url.scheme == 'https' and url.hostname == urlsplit(target_url).hostname:
                    route.continue_()
                else:
                    route.abort()
            page.route('**/*', guard)
            response = page.goto(target_url, wait_until='domcontentloaded', timeout=20000)
            result = {'target': target, 'url': target_url, 'http_status': response.status if response else None,
                      'title': page.title()[:180], 'headings': page.locator('h1').all_text_contents()[:8],
                      'viewport': 'mobile 390x844'}
            return result
        finally:
            browser.close()


def _due_schedules():
    with conn() as db:
        db.execute('BEGIN IMMEDIATE')
        stamp = int(time.time())
        due = db.execute('SELECT * FROM operation_schedules WHERE enabled=1 AND next_due<=? LIMIT 10', (stamp,)).fetchall()
        for item in due:
            # Advance to future even if worker was offline for days (no massive backlog).
            db.execute('UPDATE operation_schedules SET next_due=? WHERE id=?', (stamp + item['interval_minutes']*60, item['id']))
            db.execute('INSERT INTO operation_jobs(id,kind,options_json,status,created_at,schedule_id) VALUES(?,?,?,?,?,?)',
                       (str(uuid.uuid4()), item['kind'], item['options_json'], 'queued', now(), item['id']))


def tick():
    _due_schedules()
    item = _claim()
    if not item:
        return False
    try:
        output = run_task(item['kind'], json.loads(item['options_json']))
        if not isinstance(output, dict):
            raise RuntimeError('Worker returned invalid result')
    except Exception as exc:
        # Retry read-only tasks at most twice; no secret-containing exception reprs.
        error = f'{type(exc).__name__}: task failed'
        with conn() as db:
            status = 'failed' if item['attempts'] + 1 >= MAX_ATTEMPTS else 'queued'
            db.execute('UPDATE operation_jobs SET status=?,error=?,finished_at=?,lease_until=NULL WHERE id=?',
                       (status, error, now() if status == 'failed' else None, item['id']))
    else:
        with conn() as db:
            db.execute("UPDATE operation_jobs SET status='completed',result_json=?,finished_at=?,error=NULL,lease_until=NULL WHERE id=?",
                       (json.dumps(output)[:25000], now(), item['id']))
    return True


def start_worker():
    global WORKER
    with conn():
        pass
    if WORKER and WORKER.is_alive():
        return
    STOP.clear()
    def loop():
        while not STOP.is_set():
            try:
                busy = tick()
            except Exception:
                busy = False
            STOP.wait(0.1 if busy else RUNNER_INTERVAL)
    WORKER = threading.Thread(target=loop, name='ESN-Operations', daemon=True)
    WORKER.start()


def _auth(handler):
    token = connections.token_from_cookie(handler.headers.get('Cookie', ''))
    return handler.authorized() or connections.session_valid(token)


def _csrf(handler):
    if handler.authorized():
        return True
    token = connections.token_from_cookie(handler.headers.get('Cookie', ''))
    return connections.session_valid(token) and handler.headers.get('Origin', '') == connections.PUBLIC_ORIGIN and hmac.compare_digest(handler.headers.get('X-ESN-CSRF', ''), connections.csrf_token(token))


def handle(handler):
    from urllib.parse import urlsplit as split
    path = split(handler.path).path
    if path != '/tasks' and not path.startswith('/api/operations'):
        return False
    if not _auth(handler):
        handler.send_json(401, {'error': 'Sign in to Connections first'})
        return True
    if path == '/tasks' and handler.command == 'GET':
        handler.send_html((Path(__file__).with_name('web') / 'tasks.html').read_bytes())
        return True
    if handler.command == 'GET':
        if path == '/api/operations':
            handler.send_json(200, {'jobs': jobs(), 'schedules': schedules(), 'kinds': sorted(TASK_KINDS), 'intervals': sorted(INTERVALS)})
            return True
        if path == '/api/operations/resources':
            import resources
            handler.send_json(200, resources.snapshot())
            return True
    if handler.command == 'POST':
        if not _csrf(handler):
            handler.send_json(403, {'error': 'Request rejected'}); return True
        try:
            body = connections.read_json(handler)
            if path == '/api/operations/jobs':
                ident = enqueue(body.get('kind'), body.get('options'))
                handler.send_json(202, {'job_id': ident, 'status': 'queued'}); return True
            if path == '/api/operations/schedules':
                ident = schedule(body.get('kind'), body.get('interval_minutes'), body.get('options'))
                handler.send_json(201, {'schedule_id': ident}); return True
            if path == '/api/operations/cancel':
                handler.send_json(200, {'status': cancel(body.get('id'))}); return True
            if path == '/api/operations/pause':
                pause_schedule(body.get('id'))
                handler.send_json(200, {'status': 'paused'}); return True
        except (ValueError, TypeError, KeyError) as exc:
            handler.send_json(400, {'error': str(exc)[:160]}); return True
    handler.send_json(404, {'error': 'Not found'}); return True
