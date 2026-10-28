"""ESN Jarvis Step 53: durable, owner-approved read-only multi-step workflows.

This is an explicitly bounded automation engine, not a shell/production agent.
Only hardcoded safe operations can execute. No model output, URLs, command strings,
payment instructions, or user-supplied tool names are ever executed.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hmac
import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import connections
import operations

SAFE_KINDS = (
    "panel_health",
    "esn_website_health",
    "github_repo_health",
    "nodes_snapshot",
    "servers_snapshot",
)
MAX_STEPS = 5
MAX_ATTEMPTS = 2
MAX_ACTIVE = 8
MAX_GOAL_CHARS = 240
LEASE_SECONDS = 180
WORKER = None
STOP = threading.Event()
SCHEMA = """
CREATE TABLE IF NOT EXISTS autonomous_plans (
 id TEXT PRIMARY KEY, goal TEXT NOT NULL, status TEXT NOT NULL,
 created_at TEXT NOT NULL, approved_at TEXT, finished_at TEXT,
 error TEXT
);
CREATE INDEX IF NOT EXISTS autonomous_plan_status ON autonomous_plans(status, created_at);
CREATE TABLE IF NOT EXISTS autonomous_steps (
 plan_id TEXT NOT NULL, position INTEGER NOT NULL, kind TEXT NOT NULL,
 status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 started_at TEXT, finished_at TEXT, lease_until INTEGER,
 result_json TEXT, error TEXT,
 PRIMARY KEY(plan_id, position),
 FOREIGN KEY(plan_id) REFERENCES autonomous_plans(id)
);
CREATE INDEX IF NOT EXISTS autonomous_step_status ON autonomous_steps(status, lease_until);
"""

# Only recognize explicit requests to check or report real ESN infrastructure.
INTENT = re.compile(r"\b(check|audit|health|monitor|inspect|status|verify|report|uptime|diagnos\w*)\b", re.I)
UNSAFE = re.compile(
    r"\b(delete|remove|destroy|wipe|shutdown|reboot|restart|"
    r"suspend|unsuspend|install|upgrade|edit|modify|change|"
    r"deploy|provision|create\s+(?:a\s+)?server|"
    r"refund|charge|pay|purchase|transfer|"
    r"change\s+dns|bypass|captcha|"
    r"send\s+messages?|mass\s+dm|execute|run\s+(?:shell|code|command))\b", re.I
)
TARGET_PATTERNS = (
    ("panel_health", re.compile(r"\b(panel|pterodactyl)\b", re.I)),
    ("esn_website_health", re.compile(r"\b(website|web\s+site|homepage|esnoffical\.com)\b", re.I)),
    ("github_repo_health", re.compile(r"\b(github|repository|repo)\b", re.I)),
    ("nodes_snapshot", re.compile(r"\b(nodes?)\b", re.I)),
    ("servers_snapshot", re.compile(r"\b(servers?|customer\s+instances?)\b", re.I)),
)


def now():
    return datetime.now(timezone.utc).isoformat()


def _db():
    import jarvis  # late import keeps the existing router import graph safe
    db = sqlite3.connect(jarvis.DB_PATH, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=30000")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    return db


@contextmanager
def conn():
    db = _db()
    try:
        yield db
    finally:
        db.close()


def steps_for_goal(goal):
    """Derive an auditable *preview* from approved ESN read-only targets.

    The model cannot smuggle instructions into the executor. Unsupported
    requests are refused rather than silently reduced to a harmless subset.
    """
    if not isinstance(goal, str) or not 1 <= len(goal.strip()) <= MAX_GOAL_CHARS:
        raise ValueError("Goal must contain 1 to 240 characters")
    goal = " ".join(goal.split())
    # Reuse the existing token detector; never persist credentials in a goal.
    from agent import sanitize_message
    sanitize_message(goal)
    if UNSAFE.search(goal):
        raise ValueError("This version only supports read-only audits; no changes or commands")
    if not INTENT.search(goal):
        raise ValueError("Ask Jarvis to check, audit, verify or report ESN service health")
    selected = [kind for kind, regex in TARGET_PATTERNS if regex.search(goal)]
    if not selected and re.search(r"\b(esn|hosting|infrastructure|everything|all)\b", goal, re.I):
        selected = ["panel_health", "esn_website_health", "github_repo_health"]
    if not selected:
        raise ValueError("Name an ESN target: panel, website, GitHub, nodes or servers")
    if len(selected) > MAX_STEPS:
        raise ValueError("Too many steps in the requested audit")
    # Revalidate against the independent executor's allowlist.
    if any(kind not in SAFE_KINDS or kind not in operations.TASK_KINDS for kind in selected):
        raise ValueError("Unsupported audit task")
    for kind in selected:
        operations.validate(kind, {})
    return selected


def create(goal):
    selected = steps_for_goal(goal)
    clean_goal = " ".join(goal.split())
    ident = str(uuid.uuid4())
    with conn() as db:
        db.execute("BEGIN IMMEDIATE")
        count = db.execute(
            "SELECT COUNT(*) FROM autonomous_plans WHERE status IN ('awaiting_approval','running')"
        ).fetchone()[0]
        if count >= MAX_ACTIVE:
            raise ValueError("Too many active plans; complete or cancel one first")
        db.execute(
            "INSERT INTO autonomous_plans(id,goal,status,created_at) VALUES(?,?,?,?)",
            (ident, clean_goal, "awaiting_approval", now()),
        )
        for position, kind in enumerate(selected):
            db.execute(
                "INSERT INTO autonomous_steps(plan_id,position,kind,status) VALUES(?,?,?,?)",
                (ident, position, kind, "queued"),
            )
        db.commit()
    return ident


def _identifier(ident):
    if not isinstance(ident, str):
        raise ValueError("Invalid plan ID")
    try:
        return str(uuid.UUID(ident))
    except (ValueError, AttributeError):
        raise ValueError("Invalid plan ID") from None


def approve(ident):
    ident = _identifier(ident)
    with conn() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT status FROM autonomous_plans WHERE id=?", (ident,)).fetchone()
        if not row:
            raise KeyError("Plan not found")
        if row["status"] != "awaiting_approval":
            raise ValueError("Only plans awaiting approval may be started")
        db.execute(
            "UPDATE autonomous_plans SET status='running',approved_at=? WHERE id=?",
            (now(), ident),
        )
        db.commit()
    return "running"


def cancel(ident):
    ident = _identifier(ident)
    with conn() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT status FROM autonomous_plans WHERE id=?", (ident,)).fetchone()
        if not row:
            raise KeyError("Plan not found")
        if row["status"] not in ("awaiting_approval", "running"):
            db.commit()
            return row["status"]
        db.execute(
            "UPDATE autonomous_plans SET status='cancelled',finished_at=? WHERE id=?",
            (now(), ident),
        )
        # An in-flight read-only HTTP request cannot be interrupted safely.
        db.execute(
            "UPDATE autonomous_steps SET status='cancelled',finished_at=? "
            "WHERE plan_id=? AND status='queued'", (now(), ident)
        )
        db.commit()
    return "cancelled"


def _details(db, plan_row):
    result = dict(plan_row)
    rows = db.execute(
        "SELECT position,kind,status,attempts,started_at,finished_at,result_json,error "
        "FROM autonomous_steps WHERE plan_id=? ORDER BY position", (result["id"],)
    ).fetchall()
    result["steps"] = []
    for item in rows:
        step = dict(item)
        raw = step.pop("result_json")
        step["result"] = json.loads(raw) if raw else None
        result["steps"].append(step)
    result["completed_steps"] = sum(step["status"] == "completed" for step in result["steps"])
    result["total_steps"] = len(result["steps"])
    return result


def get(ident):
    ident = _identifier(ident)
    with conn() as db:
        row = db.execute("SELECT * FROM autonomous_plans WHERE id=?", (ident,)).fetchone()
        if not row:
            raise KeyError("Plan not found")
        return _details(db, row)


def plans(limit=12):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 30:
        raise ValueError("Invalid plan limit")
    with conn() as db:
        rows = db.execute(
            "SELECT * FROM autonomous_plans ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_details(db, row) for row in rows]


def _claim():
    with conn() as db:
        db.execute("BEGIN IMMEDIATE")
        stamp = int(time.time())
        # Read-only I/O may be repeated once after a crashed worker.
        expired = db.execute(
            "SELECT DISTINCT plan_id FROM autonomous_steps WHERE status='running' "
            "AND lease_until < ? AND attempts >= ?",
            (stamp, MAX_ATTEMPTS),
        ).fetchall()
        for row in expired:
            db.execute(
                "UPDATE autonomous_steps SET status='failed',error='Worker lease exhausted',"
                "finished_at=?,lease_until=NULL "
                "WHERE plan_id=? AND status='running' AND lease_until < ?",
                (now(), row["plan_id"], stamp),
            )
            db.execute(
                "UPDATE autonomous_plans SET status='failed',finished_at=?,error='Worker lease exhausted' "
                "WHERE id=? AND status='running'", (now(), row["plan_id"]),
            )
        db.execute(
            "UPDATE autonomous_steps SET status='queued',lease_until=NULL "
            "WHERE status='running' AND lease_until < ? AND attempts < ? "
            "AND plan_id IN (SELECT id FROM autonomous_plans WHERE status='running')",
            (stamp, MAX_ATTEMPTS),
        )
        row = db.execute(
            "SELECT s.plan_id,s.position,s.kind,s.attempts FROM autonomous_steps s "
            "JOIN autonomous_plans p ON p.id=s.plan_id "
            "WHERE p.status='running' AND s.status='queued' AND s.attempts < ? "
            "AND NOT EXISTS (SELECT 1 FROM autonomous_steps earlier "
            "WHERE earlier.plan_id=s.plan_id AND earlier.position < s.position "
            "AND earlier.status!='completed') "
            "ORDER BY p.approved_at,s.position LIMIT 1", (MAX_ATTEMPTS,)
        ).fetchone()
        if row:
            db.execute(
                "UPDATE autonomous_steps SET status='running',attempts=attempts+1,"
                "started_at=?,lease_until=? WHERE plan_id=? AND position=? AND status='queued'",
                (now(), stamp + LEASE_SECONDS, row["plan_id"], row["position"]),
            )
        db.commit()
    return dict(row) if row else None


def tick():
    """Run at most one approved, allowlisted step; status is stored durably."""
    item = _claim()
    if not item:
        return False
    plan_id, position, kind = item["plan_id"], item["position"], item["kind"]
    with conn() as db:
        state = db.execute(
            "SELECT status FROM autonomous_plans WHERE id=?", (plan_id,)
        ).fetchone()
    if not state or state["status"] != "running":
        with conn() as db:
            db.execute("UPDATE autonomous_steps SET status='cancelled',finished_at=?,"
                       "lease_until=NULL WHERE plan_id=? AND position=? AND status='running'",
                       (now(), plan_id, position))
        return True
    try:
        if kind not in SAFE_KINDS:
            raise ValueError("Disallowed step kind")
        operations.validate(kind, {})
        output = operations.run_task(kind, {})
        if not isinstance(output, dict):
            raise ValueError("Invalid result")
        serialized = json.dumps(output, ensure_ascii=True)
        if len(serialized) > 15000:
            raise ValueError("Result too large")
    except Exception as exc:
        # Never persist a provider exception message that might contain secrets.
        fail = f"{type(exc).__name__}: read-only step failed"
        with conn() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT status FROM autonomous_plans WHERE id=?", (plan_id,)
            ).fetchone()
            if current and current["status"] == "running":
                exhausted = item["attempts"] + 1 >= MAX_ATTEMPTS
                db.execute(
                    "UPDATE autonomous_steps SET status=?,error=?,finished_at=?,lease_until=NULL "
                    "WHERE plan_id=? AND position=? AND status='running'",
                    ("failed" if exhausted else "queued", fail, now() if exhausted else None, plan_id, position),
                )
                if exhausted:
                    db.execute(
                        "UPDATE autonomous_plans SET status='failed',finished_at=?,error=? "
                        "WHERE id=? AND status='running'", (now(), fail, plan_id)
                    )
            else:
                db.execute(
                    "UPDATE autonomous_steps SET status='cancelled',finished_at=?,lease_until=NULL "
                    "WHERE plan_id=? AND position=? AND status='running'", (now(), plan_id, position)
                )
            db.commit()
    else:
        with conn() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT status FROM autonomous_plans WHERE id=?", (plan_id,)
            ).fetchone()
            if current and current["status"] == "running":
                db.execute(
                    "UPDATE autonomous_steps SET status='completed',result_json=?,"
                    "finished_at=?,error=NULL,lease_until=NULL "
                    "WHERE plan_id=? AND position=? AND status='running'",
                    (serialized, now(), plan_id, position),
                )
                left = db.execute(
                    "SELECT COUNT(*) FROM autonomous_steps WHERE plan_id=? AND status!='completed'",
                    (plan_id,),
                ).fetchone()[0]
                if left == 0:
                    db.execute(
                        "UPDATE autonomous_plans SET status='completed',finished_at=? "
                        "WHERE id=? AND status='running'", (now(), plan_id),
                    )
            else:
                db.execute(
                    "UPDATE autonomous_steps SET status='cancelled',finished_at=?,lease_until=NULL "
                    "WHERE plan_id=? AND position=? AND status='running'", (now(), plan_id, position)
                )
            db.commit()
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
                had_work = tick()
            except Exception:
                had_work = False
            STOP.wait(0.15 if had_work else 1.0)

    WORKER = threading.Thread(target=loop, name="ESN-Autonomous", daemon=True)
    WORKER.start()


def _auth(handler):
    session = connections.token_from_cookie(handler.headers.get("Cookie", ""))
    return handler.authorized() or connections.session_valid(session)


def _csrf(handler):
    if handler.authorized():
        return True
    session = connections.token_from_cookie(handler.headers.get("Cookie", ""))
    return (
        connections.session_valid(session)
        and handler.headers.get("Origin", "") == connections.PUBLIC_ORIGIN
        and hmac.compare_digest(
            handler.headers.get("X-ESN-CSRF", ""), connections.csrf_token(session)
        )
    )


def handle(handler):
    path = urlsplit(handler.path).path
    if not path.startswith("/api/autonomous"):
        return False
    if not _auth(handler):
        handler.send_json(401, {"error": "Sign in to Connections first"})
        return True
    if handler.command == "GET" and path == "/api/autonomous/plans":
        handler.send_json(200, {"plans": plans()})
        return True
    if handler.command != "POST":
        handler.send_json(404, {"error": "Not found"})
        return True
    if not _csrf(handler):
        handler.send_json(403, {"error": "Request rejected"})
        return True
    try:
        body = connections.read_json(handler)
        if path == "/api/autonomous/create":
            ident = create(body.get("goal"))
            handler.send_json(201, {"plan_id": ident, "status": "awaiting_approval"})
            return True
        if path == "/api/autonomous/approve":
            handler.send_json(200, {"status": approve(body.get("id"))})
            return True
        if path == "/api/autonomous/cancel":
            handler.send_json(200, {"status": cancel(body.get("id"))})
            return True
    except (ValueError, TypeError, KeyError) as exc:
        handler.send_json(400, {"error": str(exc)[:140]})
        return True
    handler.send_json(404, {"error": "Not found"})
    return True
