"""Jarvis host disk audit: read-only, bounded, no shell or filesystem mutation.

This reports only the VPS running Jarvis. Remote Wings nodes require a
separately authenticated, least-privilege agent; do not claim they were checked.
No customer files, Pterodactyl backups, Docker state, or secrets are read.
"""
import os
import shutil
import stat
import time
from pathlib import Path

CACHE_NAMES = ("cache", "tmp")
CACHE_BASE = Path("/opt/esn-jarvis")
AGE_SECONDS = 7 * 24 * 60 * 60
MAX_FILES = 5000
MAX_DEPTH = 5
MAX_SCAN_SECONDS = 1.25
# Never inspect these locations beyond filesystem-level aggregate capacity:
PROTECTED = (
    "/var/lib/pterodactyl/volumes",
    "/var/lib/pterodactyl/backups",
    "/var/lib/pterodactyl/archives",
    "/var/lib/docker",
    "/etc/pterodactyl",
)


def cache_summary(base=CACHE_BASE, current_time=None):
    """Scan only Jarvis-owned cache/tmp paths without following symlinks.

    Counts are estimates, not approved deletion targets; no paths or filenames
    are returned to the model or dashboard. Does not traverse mount boundaries.
    """
    root = Path(base)
    # Refuse indirection via a symlinked owner directory.
    if root.is_symlink():
        return {
            "status": "refused_symlink_root",
            "files_checked": 0,
            "total_regular_file_bytes": 0,
            "older_than_7_days_file_count": 0,
            "older_than_7_days_bytes": 0,
            "truncated": True,
            "missing_cache_dirs": [],
        }
    stamp = time.time() if current_time is None else current_time
    deadline = time.monotonic() + MAX_SCAN_SECONDS
    data = {
        "status": "inspected",
        "files_checked": 0,
        "total_regular_file_bytes": 0,
        "older_than_7_days_file_count": 0,
        "older_than_7_days_bytes": 0,
        "truncated": False,
        "missing_cache_dirs": [],
    }

    for name in CACHE_NAMES:
        cache = root / name
        try:
            if cache.is_symlink():
                data["truncated"] = True
                continue
            cache_stat = cache.lstat()
            if not stat.S_ISDIR(cache_stat.st_mode):
                data["truncated"] = True
                continue
        except FileNotFoundError:
            data["missing_cache_dirs"].append(name)
            continue
        except OSError:
            data["truncated"] = True
            continue

        stack = [(cache, 0)]
        while stack:
            if time.monotonic() >= deadline or data["files_checked"] >= MAX_FILES:
                data["truncated"] = True
                break
            folder, depth = stack.pop()
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        if time.monotonic() >= deadline or data["files_checked"] >= MAX_FILES:
                            data["truncated"] = True
                            break
                        # Never follow symlinks; skip hard-linked files, too.
                        try:
                            info = entry.stat(follow_symlinks=False)
                        except OSError:
                            data["truncated"] = True
                            continue
                        if info.st_dev != cache_stat.st_dev:
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            if depth < MAX_DEPTH:
                                stack.append((Path(entry.path), depth + 1))
                            else:
                                data["truncated"] = True
                        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                            data["files_checked"] += 1
                            data["total_regular_file_bytes"] += max(0, info.st_size)
                            if 0 <= stamp - info.st_mtime and stamp - info.st_mtime >= AGE_SECONDS:
                                data["older_than_7_days_file_count"] += 1
                                data["older_than_7_days_bytes"] += max(0, info.st_size)
            except OSError:
                data["truncated"] = True
                continue
        if data["truncated"]:
            break
    return data


def report(mount="/", cache_base=CACHE_BASE):
    """Report host-level mount space and safely bounded Jarvis cache estimates.

    Arguments are for tests only. The public/Discord entry points NEVER accept
    custom paths or hostnames.
    """
    usage = shutil.disk_usage(mount)
    total, used, free = usage.total, usage.used, usage.free
    free_percent = round(free * 100 / total, 1) if total else 0.0
    used_percent = round(used * 100 / total, 1) if total else 0.0
    cache = cache_summary(cache_base)
    return {
        "scope": "local_jarvis_vps_only",
        "mount": "/",
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "used_percent": used_percent,
        "free_percent": free_percent,
        "disk_pressure": "critical" if free_percent < 10 else "warning" if free_percent < 20 else "normal",
        "jarvis_owned_cache": cache,
        "cleanup_executed": False,
        "remote_nodes_checked": 0,
        "note": (
            "This is the Jarvis host's root filesystem, NOT all ESN nodes. "
            "Old Jarvis cache sizes are estimates; no files were deleted. "
            "Customer servers, Wings backups, Docker layers and production data are excluded."
        ),
    }
