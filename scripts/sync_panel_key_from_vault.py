#!/usr/bin/env python3
"""One-time mobile-friendly ESN panel credential sync.

Reads an already-encrypted Pterodactyl credential from Jarvis Connections
and validates it against the fixed official panel endpoint BEFORE updating
the protected systemd environment file. Never prints the credential.
No nano, interactive password prompt, service restart or panel mutation.
"""
import json
import os
import sqlite3
from pathlib import Path
import re
import stat
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener
from cryptography.fernet import Fernet, InvalidToken

ENV_PATH = Path("/etc/esn-jarvis.env")
PANEL_NODES_URL = "https://panel.esnoffical.com/api/application/nodes?per_page=1"
EXPECTED_LABEL = "ESN Jarvis Customer Capacity"


class RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _read_protected_env(path=ENV_PATH):
    p = Path(path)
    fd = os.open(p, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise RuntimeError("Jarvis environment must be a regular private 0600 file")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            lines = stream.read(65537).splitlines()
            fd = -1
        if sum(len(x) for x in lines) > 65536:
            raise RuntimeError("Jarvis environment is unexpectedly large")
    finally:
        if fd != -1:
            os.close(fd)
    variables = {}
    for line in lines:
        record = line.strip()
        if not record or record.startswith("#"):
            continue
        if record.startswith("export "):
            record = record[len("export "):]
        name, equal, value = record.partition("=")
        if equal and re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            variables[name] = value
    if not variables.get("ESN_VAULT_KEY") or not os.path.isabs(variables.get("ESN_DB_PATH", "")):
        raise RuntimeError("Jarvis vault key or absolute database path missing from private env")
    panel_url = variables.get("PTERO_BASE_URL", "https://panel.esnoffical.com").rstrip("/")
    if panel_url != "https://panel.esnoffical.com":
        raise RuntimeError("Configured panel URL is not the official ESN Panel")
    return lines, variables, info


def _get_saved_key(variables):
    """Read one encrypted vault record directly in SQLite read-only mode.

    Do not import Jarvis's user-writable app code as root. This helper
    only needs the audited vault schema and the standard Fernet decryptor.
    """
    location = Path(variables["ESN_DB_PATH"])
    if location.is_symlink() or not location.is_file():
        raise RuntimeError("Encrypted Jarvis vault database not found safely")
    if location.stat().st_mode & 0o002:
        raise RuntimeError("Refusing world-writable vault database")
    try:
        with sqlite3.connect("file:" + location.as_uri().split("file:", 1)[-1] +
                             "?mode=ro", uri=True, timeout=5) as db:
            rows = db.execute(
                "SELECT label, secret_blob FROM vault_connections "
                "WHERE kind='pterodactyl' ORDER BY created_at DESC LIMIT 101"
            ).fetchall()
    except sqlite3.Error:
        raise RuntimeError("Could not read encrypted Jarvis vault") from None
    matches = [row for row in rows if row[0] == EXPECTED_LABEL]
    if len(matches) == 1:
        selected = matches[0]
    elif not matches and len(rows) == 1:
        selected = rows[0]
    else:
        raise RuntimeError(
            "Cannot safely select a unique saved Pterodactyl connection. "
            "Keep only one or label it 'ESN Jarvis Customer Capacity'."
        )
    try:
        secret = Fernet(variables["ESN_VAULT_KEY"].encode("ascii")).decrypt(selected[1]).decode("utf-8")
    except (InvalidToken, ValueError, TypeError, UnicodeError):
        raise RuntimeError("Encrypted Jarvis credential could not be decrypted") from None
    if not secret.startswith("ptla_") or not 25 <= len(secret) <= 1000 or any(c.isspace() for c in secret):
        raise RuntimeError("Saved connection is not a valid-format Application API key")
    return secret


def _verify_panel_key(secret):
    request = Request(PANEL_NODES_URL, headers={
        "Authorization": "Bearer " + secret,
        "Accept": "Application/vnd.pterodactyl.v1+json",
        "User-Agent": "ESN-Jarvis-VaultSync/0.1",
    }, method="GET")
    try:
        with build_opener(RejectRedirect()).open(request, timeout=12) as response:
            if response.status != 200:
                raise RuntimeError("ESN Panel did not accept the API key")
            data = response.read(262145)
    except HTTPError as exc:
        if exc.code == 401:
            raise RuntimeError("ESN Panel rejected the saved key (401). Recheck Application API key.") from None
        if exc.code == 403:
            raise RuntimeError("ESN Panel key lacks Nodes Read permission (403).") from None
        raise RuntimeError("ESN Panel API validation failed (HTTP %d)" % exc.code) from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("Unable to verify ESN Panel API over HTTPS") from None
    if len(data) > 262144:
        raise RuntimeError("ESN Panel validation response too large")
    try:
        document = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise RuntimeError("ESN Panel returned invalid JSON") from None
    if not isinstance(document, dict) or not isinstance(document.get("data"), list):
        raise RuntimeError("ESN Panel did not return a node listing")
    return True


def sync(path=ENV_PATH):
    if os.geteuid() != 0:
        raise RuntimeError("Run this command as root through Termius")
    p = Path(path)
    if p.is_symlink():
        raise RuntimeError("Refusing symlinked Jarvis environment")
    lines, variables, info = _read_protected_env(p)
    secret = _get_saved_key(variables)
    _verify_panel_key(secret)  # no config write until the new credential works
    remaining = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("export "):
            stripped = stripped[len("export "):]
        if not stripped.startswith("PTERO_API_KEY="):
            remaining.append(line)
    remaining.append("PTERO_API_KEY=" + secret)
    fd, temp = tempfile.mkstemp(dir=p.parent, prefix=".esn-panel-key-")
    try:
        os.fchmod(fd, 0o600)
        os.fchown(fd, info.st_uid, info.st_gid)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            fd = -1
            stream.write("\n".join(remaining) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if p.is_symlink() or p.stat().st_ino != info.st_ino:
            raise RuntimeError("Jarvis env changed during synchronization; refusing")
        os.replace(temp, p)
        temp = None
    finally:
        if fd != -1:
            os.close(fd)
        if temp and os.path.exists(temp):
            os.unlink(temp)
    print("SUCCESS: Encrypted vault key validated against ESN Panel and saved in protected env.")
    print("No API key displayed, no Jarvis restart, and no panel settings modified.")


def main():
    try:
        sync()
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
