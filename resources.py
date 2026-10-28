"""Read-only cgroup v2 memory budget introspection for ESN Jarvis.

Only the fixed ESN Jarvis slice path is inspected; no user-supplied paths,
credentials, shell execution or host-wide process listing.
"""
from pathlib import Path

BUDGET_BYTES = 8 * 1024**3
SLICE = Path("/sys/fs/cgroup/esn-jarvis.slice")


def _number(path):
    try:
        value = path.read_text(encoding="ascii").strip()
        return None if value == "max" else int(value)
    except (OSError, UnicodeError, ValueError):
        return None


def snapshot(slice_path=SLICE):
    """Return safe public numbers *only after the owner API is authenticated*."""
    root = Path(slice_path)
    current = _number(root / "memory.current")
    maximum = _number(root / "memory.max")
    high = _number(root / "memory.high")
    events = {}
    try:
        for line in (root / "memory.events").read_text(encoding="ascii").splitlines():
            k, sep, v = line.partition(" ")
            if sep and k in {"high", "max", "oom", "oom_kill"}:
                events[k] = int(v.strip())
    except (OSError, ValueError, UnicodeError):
        events = {}
    return {
        "slice_present": root.is_dir(),
        "shared_cap_active": root.is_dir() and maximum == BUDGET_BYTES,
        "budget_bytes": BUDGET_BYTES,
        "used_bytes": current,
        "effective_max_bytes": maximum,
        "throttle_above_bytes": high,
        "usage_percent": round(100 * current / BUDGET_BYTES, 1) if current is not None else None,
        "events": events,
        "note": "Only services assigned to esn-jarvis.slice count. Verify service Slice= after restarting each service.",
    }
