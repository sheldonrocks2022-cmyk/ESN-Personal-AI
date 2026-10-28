"""Owner-authenticated managed Discord bot REST tools.

Tokens are saved only in the existing encrypted Connections vault. These
tools never use a normal Discord user token or inspect Pterodactyl containers.
Messages are one-by-one, explicitly approved, guild-only, and rate limited.
"""
import hmac
import json
import os
import re
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

import connections

DISCORD_API = "https://discord.com/api/v10"
DAILY_PER_BOT = 10
DAILY_TOTAL = 30
COOLDOWN_SECONDS = 30
MAX_MESSAGE_LENGTH = 1200

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _discord_request(path, token, payload=None):
    if not isinstance(token, str) or not token or "\n" in token or "\r" in token:
        raise RuntimeError("Invalid stored bot credential")
    # Must be a fixed trusted path, never a caller-provided URL.
    if not path.startswith(("/users/@me", "/channels/")) or any(c in path for c in "?#\\"):
        raise ValueError("Unsupported Discord endpoint")
    headers = {"Authorization": "Bot " + token, "Accept": "application/json",
               "User-Agent": "ESN-Jarvis-ManagedBot/0.6"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = Request(DISCORD_API + path, method="POST" if payload is not None else "GET",
                  headers=headers,
                  data=json.dumps(payload).encode("utf-8") if payload is not None else None)
    try:
        with build_opener(NoRedirect()).open(req, timeout=10) as resp:
            raw = resp.read(65537)
        if len(raw) > 65536:
            raise RuntimeError("Discord response too large")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise RuntimeError("Unexpected Discord API response")
        return value
    except HTTPError as exc:
        # HTTP only; never echo token, body, channel messages or provider headers.
        if exc.code in (401, 403):
            raise RuntimeError("Bot credential invalid or missing required permissions") from None
        if exc.code == 429:
            raise RuntimeError("Discord rate limit reached; try again later") from None
        raise RuntimeError("Discord API request unsuccessful") from None
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError, OSError):
        raise RuntimeError("Discord API unavailable or invalid response") from None


def _snowflake(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{15,21}", value) or int(value) == 0:
        raise ValueError("Provide a numeric Discord channel ID")
    return value


def _connection(ident):
    if not isinstance(ident, str) or not 8 <= len(ident) <= 100:
        raise ValueError("Invalid connection ID")
    with connections.db() as db:
        row = db.execute(
            "SELECT id,kind,label FROM vault_connections WHERE id=?", (ident,)
        ).fetchone()
    if not row or row["kind"] != "discord_bot":
        raise ValueError("Choose a saved Discord bot connection")
    return dict(row)


def list_bots():
    return [{"id": item["id"], "label": item["label"]}
            for item in connections.list_connections() if item["kind"] == "discord_bot"][:20]


def identity(ident):
    row = _connection(ident)
    obj = _discord_request("/users/@me", connections.read_secret_local(ident))
    if not obj.get("bot") or not str(obj.get("id", "")).isdigit():
        raise RuntimeError("Credential did not authenticate a Discord bot")
    return {"connection_id": ident, "connection_name": row["label"],
            "bot_id": str(obj["id"]), "bot_name": str(obj.get("username") or "")[:80],
            "connected": True}


def channel_preview(ident, channel_id):
    _connection(ident)
    channel_id = _snowflake(channel_id)
    obj = _discord_request("/channels/" + channel_id,
                           connections.read_secret_local(ident))
    # Discord 0 = guild text, 5 = guild announcement.
    if obj.get("type") not in (0, 5) or not str(obj.get("guild_id", "")).isdigit():
        raise ValueError("Only channels in authorized Discord guilds are allowed; no DMs")
    guild_id = str(obj["guild_id"])
    allowed = [x.strip() for x in os.environ.get("ESN_MANAGED_GUILD_IDS", "").split(",") if x.strip()]
    if allowed and guild_id not in allowed:
        raise ValueError("Guild is not on the owner's explicit allowed-guild list")
    return {"channel_id": channel_id, "guild_id": guild_id,
            "channel_name": str(obj.get("name") or "")[:80],
            "channel_type": "announcement" if obj["type"] == 5 else "text",
            "eligible": True}


def _admit(db, ident, channel_id):
    stamp = int(time.time())
    db.execute("""CREATE TABLE IF NOT EXISTS managed_bot_sends (
        id INTEGER PRIMARY KEY AUTOINCREMENT, connection_id TEXT NOT NULL,
        channel_id TEXT NOT NULL, created_epoch INTEGER NOT NULL
    )""")
    db.execute("DELETE FROM managed_bot_sends WHERE created_epoch < ?", (stamp - 8 * 86400,))
    per = db.execute(
        "SELECT COUNT(*) FROM managed_bot_sends WHERE connection_id=? AND created_epoch>?",
        (ident, stamp - 86400)
    ).fetchone()[0]
    total = db.execute(
        "SELECT COUNT(*) FROM managed_bot_sends WHERE created_epoch>?", (stamp - 86400,)
    ).fetchone()[0]
    latest = db.execute(
        "SELECT MAX(created_epoch) FROM managed_bot_sends WHERE connection_id=?", (ident,)
    ).fetchone()[0]
    if per >= DAILY_PER_BOT or total >= DAILY_TOTAL:
        raise ValueError("Daily managed-bot message limit reached")
    if latest is not None and stamp - latest < COOLDOWN_SECONDS:
        raise ValueError("Managed-bot cooldown active")
    # Count the attempt before the network request to avoid concurrent oversending.
    db.execute(
        "INSERT INTO managed_bot_sends(connection_id,channel_id,created_epoch) VALUES(?,?,?)",
        (ident, channel_id, stamp),
    )


def send_one(ident, channel_id, content, *, confirm=False):
    if confirm is not True:
        raise ValueError("Explicit confirmation is required for every bot message")
    if not isinstance(content, str) or not 1 <= len(content.strip()) <= MAX_MESSAGE_LENGTH:
        raise ValueError("Send a message of 1–1200 characters")
    message = content.strip()
    # No mention pinging, no impersonation of the Jarvis owner.
    if any(part in message for part in ("@everyone", "@here", "<@")):
        raise ValueError("Mentions are disabled for managed-bot messages")
    preview = channel_preview(ident, channel_id)
    with connections.db() as db:
        db.execute("BEGIN IMMEDIATE")
        _admit(db, ident, preview["channel_id"])
    result = _discord_request(
        "/channels/" + preview["channel_id"] + "/messages",
        connections.read_secret_local(ident),
        {"content": message, "allowed_mentions": {"parse": []}},
    )
    if not str(result.get("id", "")).isdigit():
        raise RuntimeError("Discord did not confirm the new message")
    return {"sent": True, "message_id": str(result["id"]),
            "channel_id": preview["channel_id"],
            "guild_id": preview["guild_id"]}


def _auth(handler):
    import jarvis
    raw = handler.headers.get("Authorization", "")
    owner = bool(jarvis.OWNER_TOKEN and len(jarvis.OWNER_TOKEN) >= 32 and
                 hmac.compare_digest(raw, "Bearer " + jarvis.OWNER_TOKEN))
    token = connections.token_from_cookie(handler.headers.get("Cookie", ""))
    return owner or connections.session_valid(token)


def _csrf(handler):
    import jarvis
    raw = handler.headers.get("Authorization", "")
    if jarvis.OWNER_TOKEN and len(jarvis.OWNER_TOKEN) >= 32 and \
            hmac.compare_digest(raw, "Bearer " + jarvis.OWNER_TOKEN):
        return True
    token = connections.token_from_cookie(handler.headers.get("Cookie", ""))
    return (connections.session_valid(token)
            and handler.headers.get("Origin", "") == connections.PUBLIC_ORIGIN
            and hmac.compare_digest(handler.headers.get("X-ESN-CSRF", ""),
                                    connections.csrf_token(token)))


def handle(handler):
    path = urlsplit(handler.path).path
    if path not in ("/bots", "/api/bots", "/api/bots/identity",
                    "/api/bots/channel", "/api/bots/send"):
        return False
    if path == "/bots" and handler.command == "GET":
        token = connections.token_from_cookie(handler.headers.get("Cookie", ""))
        if not connections.session_valid(token):
            handler.send_response(302)
            handler.send_header("Location", "/connections")
            handler.send_header("Content-Length", "0")
            handler.send_header("Cache-Control", "no-store")
            handler.end_headers()
            return True
        from pathlib import Path
        handler.send_html((Path(__file__).with_name("web") / "bots.html").read_bytes())
        return True
    if not _auth(handler):
        handler.send_json(401, {"error": "Sign in to Jarvis first"})
        return True
    if handler.command == "GET" and path == "/api/bots":
        handler.send_json(200, {"bots": list_bots()})
        return True
    if handler.command != "POST" or not _csrf(handler):
        handler.send_json(403, {"error": "Action requires owner authentication and CSRF verification"})
        return True
    try:
        data = connections.read_json(handler)
        if path == "/api/bots/identity":
            handler.send_json(200, identity(data.get("connection_id")))
        elif path == "/api/bots/channel":
            handler.send_json(200, channel_preview(data.get("connection_id"),
                                                    data.get("channel_id")))
        elif path == "/api/bots/send":
            handler.send_json(200, send_one(
                data.get("connection_id"), data.get("channel_id"),
                data.get("content"), confirm=data.get("confirm")))
        else:
            handler.send_json(404, {"error": "Not found"})
    except (ValueError, TypeError, KeyError) as exc:
        handler.send_json(400, {"error": str(exc)[:140]})
    except RuntimeError:
        handler.send_json(503, {"error": "Discord bot operation failed; verify token and permissions"})
    return True
