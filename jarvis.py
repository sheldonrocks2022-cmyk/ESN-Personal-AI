"""ESN Jarvis v0.1: owner-only, read-only ESN operations and AI chat.

No production server mutations. Defaults to loopback binding.
"""
import hmac
import json
import os
import sqlite3
import threading
import uuid

import connections
import creative
import operations
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ALLOWED_JOBS = frozenset({"panel_health", "nodes_snapshot", "servers_snapshot"})
DB_PATH = os.environ.get("ESN_DB_PATH", "esn_jarvis.sqlite3")
PANEL_URL = os.environ.get("PTERO_BASE_URL", "https://panel.esnoffical.com").rstrip("/")
PTERO_KEY = os.environ.get("PTERO_API_KEY", "")
OWNER_TOKEN = os.environ.get("ESN_OWNER_TOKEN", "")
AI_KEY = os.environ.get("OPENAI_API_KEY", "")
AI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def database():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, finished_at TEXT, result_json TEXT, error TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL)")
    conn.commit()
    return conn


def clean_panel_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("PTERO_BASE_URL must be an HTTPS origin without credentials or a path")
    return url.rstrip("/")


def fetch_json(url, bearer=None, payload=None):
    headers = {"Accept": "application/json", "User-Agent": "ESN-Jarvis/0.1"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=json.dumps(payload).encode() if payload is not None else None, headers=headers, method="POST" if payload is not None else "GET")
    try:
        with urlopen(req, timeout=12) as response:
            return response.status, response.read(1024 * 1024).decode("utf-8")
    except HTTPError as exc:
        # Keep the HTTP status, but never expose upstream response bodies.
        raise RuntimeError(f"Upstream returned HTTP {exc.code}") from None
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Upstream request failed: {type(exc).__name__}") from None


def run_panel_job(kind):
    panel = clean_panel_url(PANEL_URL)
    if kind == "panel_health":
        status, _ = fetch_json(panel + "/auth/login")
        return {"reachable": 200 <= status < 400, "http_status": status}
    if kind not in ALLOWED_JOBS:
        raise ValueError("Unsupported task type")
    if not PTERO_KEY:
        raise RuntimeError("PTERO_API_KEY is not configured")
    endpoint = "nodes" if kind == "nodes_snapshot" else "servers"
    status, body = fetch_json(panel + "/api/application/" + endpoint, bearer=PTERO_KEY)
    data = json.loads(body)
    if status != 200 or not isinstance(data.get("data"), list):
        raise RuntimeError("Unexpected Pterodactyl response")
    fields = ("id", "name", "maintenance_mode") if endpoint == "nodes" else ("id", "name", "suspended", "node")
    items = [{key: item.get("attributes", {}).get(key) for key in fields} for item in data["data"]]
    return {"type": endpoint, "items": items, "page_count": len(items), "pagination": data.get("meta", {}).get("pagination", {})}


def submit_job(kind):
    if kind not in ALLOWED_JOBS:
        raise ValueError("Unsupported task type")
    job_id = str(uuid.uuid4())
    with database() as conn:
        conn.execute("INSERT INTO jobs (id,kind,status,created_at) VALUES (?,?,?,?)", (job_id, kind, "queued", utc_now()))
    threading.Thread(target=execute_job, args=(job_id, kind), daemon=True).start()
    return job_id


def execute_job(job_id, kind):
    with database() as conn:
        conn.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
    try:
        result = run_panel_job(kind)
    except Exception as exc:
        # Never persist URLs containing credentials or upstream content.
        with database() as conn:
            conn.execute("UPDATE jobs SET status='failed', finished_at=?, error=? WHERE id=?", (utc_now(), str(exc)[:160], job_id))
    else:
        with database() as conn:
            conn.execute("UPDATE jobs SET status='completed', finished_at=?, result_json=? WHERE id=?", (utc_now(), json.dumps(result), job_id))


def history(limit=12):
    with database() as conn:
        records = conn.execute("SELECT role,content FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in reversed(records)]


def chat(message):
    if not AI_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    if not isinstance(message, str) or not 1 <= len(message) <= 4000:
        raise ValueError("message must contain 1 to 4000 characters")
    context = history(12)
    system = "You are ESN Jarvis, a private assistant. You have no direct execution tools in chat yet. Never claim to have run tasks, inspected live infrastructure, or deployed code unless the verified job system supplies evidence. Do not request passwords or secrets in chat. Recommend owner-approved actions when needed."
    payload = {"model": AI_MODEL, "messages": [{"role": "system", "content": system}, *context, {"role": "user", "content": message}], "max_tokens": 700}
    _, body = fetch_json("https://api.openai.com/v1/chat/completions", bearer=AI_KEY, payload=payload)
    reply = json.loads(body)["choices"][0]["message"]["content"]
    if not isinstance(reply, str):
        raise RuntimeError("Unexpected model response")
    with database() as conn:
        conn.execute("INSERT INTO messages (role,content,created_at) VALUES (?,?,?)", ("user", message, utc_now()))
        conn.execute("INSERT INTO messages (role,content,created_at) VALUES (?,?,?)", ("assistant", reply, utc_now()))
    return reply


class Handler(BaseHTTPRequestHandler):
    server_version = "ESN-Jarvis/0.1"

    def send_html(self, body):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code, value, cookie=None):
        body = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, "Bearer " + OWNER_TOKEN)

    def deny(self):
        self.send_json(401, {"error": "Unauthorized"})

    def do_GET(self):
        if connections.handle(self):
            return
        if creative.handle(self):
            return
        if operations.handle(self):
            return
        if self.path == "/health":
            return self.send_json(200, {"service": "esn-jarvis", "status": "running", "version": "0.1"})
        if not self.authorized():
            return self.deny()
        if self.path == "/api/status":
            return self.send_json(200, {"panel": PANEL_URL, "ptero_configured": bool(PTERO_KEY), "ai_configured": bool(AI_KEY), "allowed_jobs": sorted(ALLOWED_JOBS)})
        if self.path == "/api/jobs":
            with database() as conn:
                rows = conn.execute("SELECT id,kind,status,created_at,finished_at,error FROM jobs ORDER BY created_at DESC LIMIT 30").fetchall()
            return self.send_json(200, {"jobs": [dict(row) for row in rows]})
        if self.path.startswith("/api/jobs/"):
            job_id = self.path.removeprefix("/api/jobs/")
            with database() as conn:
                row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return self.send_json(404, {"error": "Job not found"})
            value = dict(row)
            value["result"] = json.loads(value.pop("result_json")) if value["result_json"] else None
            return self.send_json(200, value)
        if self.path == "/api/memory":
            return self.send_json(200, {"messages": history(20)})
        return self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        if connections.handle(self):
            return
        if creative.handle(self):
            return
        if operations.handle(self):
            return
        if not self.authorized():
            return self.deny()
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 1 <= size <= 8192:
                return self.send_json(413, {"error": "Invalid request size"})
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                return self.send_json(400, {"error": "Expected JSON object"})
            if self.path == "/api/jobs":
                job_id = submit_job(payload.get("type"))
                return self.send_json(202, {"job_id": job_id, "status": "queued"})
            if self.path == "/api/chat":
                return self.send_json(200, {"reply": chat(payload.get("message"))})
            return self.send_json(404, {"error": "Not found"})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self.send_json(400, {"error": str(exc)[:160]})
        except (RuntimeError, KeyError, IndexError) as exc:
            return self.send_json(503, {"error": str(exc)[:160]})

    def do_DELETE(self):
        if connections.handle(self):
            return
        if creative.handle(self):
            return
        if operations.handle(self):
            return
        return self.send_json(404, {"error": "Not found"})

    def log_message(self, format, *args):
        # Omit potentially sensitive query paths and headers from access logs.
        pass


def main():
    if len(OWNER_TOKEN) < 32:
        raise SystemExit("Set ESN_OWNER_TOKEN to a random secret of at least 32 characters")
    clean_panel_url(PANEL_URL)
    connections.validate_configuration()
    with database() as conn:
        conn.execute("UPDATE jobs SET status='interrupted', finished_at=? WHERE status IN ('running','queued')", (utc_now(),))
    operations.start_worker()
    creative.start_worker()
    host = os.environ.get("ESN_BIND", "127.0.0.1")
    port = int(os.environ.get("ESN_PORT", "8765"))
    print(f"ESN Jarvis v0.4 listening at http://{host}:{port} (read-only Pterodactyl)")
    ThreadingHTTPServer((host, port), Handler).serve_forever()

if __name__ == "__main__":
    main()
