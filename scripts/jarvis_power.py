#!/usr/bin/env python3
"""ESN Jarvis root-only reversible power control.

Stops only the three known Jarvis services. Does NOT touch Wings,
Pterodactyl, customer game servers, Nginx, Docker or their files.
Disk space is not reclaimed by stopping services.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

DISCORD = "esn-jarvis-discord.service"
WEB = "esn-jarvis.service"
MODEL = "ollama.service"
SHUTDOWN_ORDER = (DISCORD, WEB, MODEL)
STARTUP_ORDER = (MODEL, WEB, DISCORD)
JARVIS_SLICE = "esnjarvis.slice"
STATE_DIR = Path("/var/lib/esn-jarvis-power")
STATE_FILE = STATE_DIR / "last-off.json"
LOCK_FILE = STATE_DIR / "power.lock"
VERSION = 1
ALLOWED_ENABLED = {"enabled", "enabled-runtime", "disabled", "static", "indirect"}
MAX_COMMAND_SECONDS = 30


def systemctl(*arguments):
    """No shell, substitutions, user-supplied service names or secrets."""
    try:
        return subprocess.run(
            ["systemctl", *arguments], capture_output=True, text=True,
            timeout=MAX_COMMAND_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("systemctl invocation failed") from exc


def must(*arguments):
    result = systemctl(*arguments)
    if result.returncode:
        # systemd messages are not printed (could contain private drop-ins).
        raise RuntimeError("systemctl " + " ".join(arguments[:2]) + " failed")
    return result.stdout.strip()


def loaded(unit):
    result = systemctl("show", unit, "--property=LoadState", "--value")
    return result.returncode == 0 and result.stdout.strip() == "loaded"


def enabled(unit):
    result = systemctl("is-enabled", unit)
    value = result.stdout.strip()
    if value not in ALLOWED_ENABLED:
        raise RuntimeError("Unsupported unit enable state for " + unit)
    return value


def active(unit):
    result = systemctl("is-active", unit)
    return result.stdout.strip() or "unknown"


def in_jarvis_slice(unit):
    result = systemctl("show", unit, "--property=Slice", "--value")
    return result.returncode == 0 and result.stdout.strip() == JARVIS_SLICE


def ensure_root():
    if os.geteuid() != 0:
        raise RuntimeError("Use root/Termius to turn Jarvis on or off")


def require_safe_target(units):
    for unit in units:
        if not loaded(unit):
            raise RuntimeError("Jarvis unit not installed: " + unit)
    if MODEL in units and not in_jarvis_slice(MODEL):
        raise RuntimeError(
            "Ollama is not currently in the Jarvis resource slice. "
            "Refusing to stop a potentially shared model server. "
            "Use 'off --keep-ollama' if it is shared."
        )


def prepare_dir():
    if STATE_DIR.is_symlink():
        raise RuntimeError("Refusing symlinked power state directory")
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    STATE_DIR.chmod(0o700)
    if STATE_FILE.is_symlink() or LOCK_FILE.is_symlink():
        raise RuntimeError("Refusing symlinked power state file")


def read_state():
    if STATE_FILE.is_symlink():
        raise RuntimeError("Refusing symlinked power state")
    if not STATE_FILE.is_file():
        return None
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Unable to read power state safely") from exc
    if (data.get("version") != VERSION or
            not isinstance(data.get("enabled"), dict) or
            not isinstance(data.get("units"), list) or
            not data["units"] or
            any(u not in SHUTDOWN_ORDER for u in data["units"]) or
            set(data["units"]) != set(data["enabled"]) or
            any(state not in ALLOWED_ENABLED for state in data["enabled"].values())):
        raise RuntimeError("Invalid saved Jarvis power state; refusing changes")
    return data


def write_state(data):
    encoded = (json.dumps(data, sort_keys=True) + "\n").encode()
    fd, name = tempfile.mkstemp(prefix=".power-", dir=str(STATE_DIR))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, STATE_FILE)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _reported_resources():
    """Read-only, host-wide capacity; not a promise to extend panel allocations."""
    try:
        disk = shutil.disk_usage("/opt/esn-jarvis")
        print("Host filesystem: %.1f GiB total, %.1f GiB free" %
              (disk.total / 1024**3, disk.free / 1024**3))
    except OSError:
        print("Host filesystem: unavailable")
    try:
        lines = Path("/proc/meminfo").read_text().splitlines()
        values = {line.split(":")[0]: int(line.split(":")[1].strip().split()[0])
                  for line in lines if ":" in line}
        print("Host RAM available now: %.2f GiB (not a Jarvis reservation)" %
              (values["MemAvailable"] * 1024 / 1024**3))
    except (OSError, KeyError, ValueError, IndexError):
        print("Host RAM available now: unavailable")


def status():
    current = read_state()
    for unit in SHUTDOWN_ORDER:
        label = "Jarvis Discord" if unit == DISCORD else ("Jarvis Web" if unit == WEB else "Jarvis Ollama AI")
        print("%s: %s; boot enablement: %s" % (
            label, active(unit),
            systemctl("is-enabled", unit).stdout.strip() or "unknown",
        ))
    print("Jarvis power mode: " + ("OFF record saved" if current else "ON / no saved OFF record"))
    if current and MODEL not in current["units"]:
        print("Ollama was intentionally left running because --keep-ollama was selected.")
    _reported_resources()
    print("Stopping Jarvis does not delete models, caches, databases or other files.")


def off(*, keep_ollama=False, dry_run=False):
    units = tuple(u for u in SHUTDOWN_ORDER if not (keep_ollama and u == MODEL))
    current = read_state()
    if current is not None:
        if set(current["units"]) != set(units):
            raise RuntimeError("Jarvis already has a saved OFF mode; use same option or turn it on first")
        if not dry_run:
            print("Resuming previously recorded shutdown; original boot settings preserved.")
    require_safe_target(units)
    if current is None:
        previous = {unit: enabled(unit) for unit in units}
        current = {"version": VERSION, "units": list(units), "enabled": previous}
    if dry_run:
        print("DRY RUN: would stop + disable: " + ", ".join(units))
        print("Would preserve boot-enable states and leave disk contents untouched.")
        return
    if not STATE_FILE.exists():
        write_state(current)
    for unit in units:
        must("disable", "--now", unit)
        print("Stopped and disabled: " + unit)
    for unit in units:
        if active(unit) in ("active", "activating"):
            raise RuntimeError(unit + " is still active; inspect its dependencies before assuming OFF")
    print("Jarvis OFF. Disk files kept for a reversible restart.")
    print("SSH/Termius remains available; use 'esnjarvis on' to restore Jarvis.")
    _reported_resources()


def on(*, dry_run=False):
    current = read_state()
    if current is None:
        raise RuntimeError(
            "No previously recorded Jarvis shutdown. Use 'esnjarvis status' "
            "rather than changing unknown service boot settings."
        )
    units = tuple(current["units"])
    require_safe_target(units)
    if dry_run:
        print("DRY RUN: would restore and start: " +
              ", ".join(u for u in STARTUP_ORDER if u in units))
        return
    for unit in STARTUP_ORDER:
        if unit not in units:
            continue
        original = current["enabled"][unit]
        if original in ("enabled", "enabled-runtime"):
            must("enable", unit)
        # Static/disabled/indirect units stay non-enabled, preserving original policy.
        must("start", unit)
        print("Started: " + unit)
    for unit in units:
        if active(unit) not in ("active",):
            raise RuntimeError("Service not active after startup: " + unit +
                               "; previous OFF record kept for safe retry")
    STATE_FILE.unlink()
    print("Jarvis ON. Web and Discord are active; allow brief startup before checking /health.")
    _reported_resources()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Reversible ESN Jarvis on/off/status controls. Never touches customer hosting units."
    )
    parser.add_argument("action", choices=("status", "off", "on"))
    parser.add_argument("--keep-ollama", action="store_true",
                        help="with off: leave potentially shared Ollama untouched")
    parser.add_argument("--dry-run", action="store_true",
                        help="preview off/on without changing any service")
    args = parser.parse_args(argv)
    if args.keep_ollama and args.action != "off":
        parser.error("--keep-ollama applies only to off")
    try:
        if args.action == "status":
            status()
        else:
            if not args.dry_run:
                ensure_root()
                prepare_dir()
                with LOCK_FILE.open("a+") as handle:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    if args.action == "off":
                        off(keep_ollama=args.keep_ollama)
                    else:
                        on()
            elif args.action == "off":
                off(keep_ollama=args.keep_ollama, dry_run=True)
            else:
                on(dry_run=True)
    except (RuntimeError, OSError, BlockingIOError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
