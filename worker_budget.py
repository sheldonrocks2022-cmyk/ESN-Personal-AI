"""Shared Jarvis job-budget guard. 50 *queued work slots*, not 50 OS processes.

Operations and autonomous plans share one SQLite database. Both writers must
BEGIN IMMEDIATE before counting and inserting their work for atomic admission.
Only the already-existing single-threaded workers execute jobs (maximum 2
read-only calls across the two independent loops).
"""
import os
import sqlite3

import resources

MAX_QUEUED_WORK = 50
MAX_CONCURRENT_READ_ONLY_CHECKS = 2
MEMORY_HEADROOM_BYTES = 256 * 1024 * 1024


def _exists(db, table):
    return bool(db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone())


def occupied_slots(db):
    """Count work actually queued or still running across both engines."""
    used = 0
    if _exists(db, "operation_jobs"):
        used += db.execute(
            "SELECT COUNT(*) FROM operation_jobs WHERE status IN ('queued','running')"
        ).fetchone()[0]
    if _exists(db, "autonomous_steps") and _exists(db, "autonomous_plans"):
        used += db.execute(
            "SELECT COUNT(*) FROM autonomous_steps s "
            "JOIN autonomous_plans p ON p.id=s.plan_id "
            "WHERE s.status IN ('queued','running') "
            "AND p.status IN ('running','awaiting_approval')"
        ).fetchone()[0]
    return used


def check_room(db, more=1):
    if isinstance(more, bool) or not isinstance(more, int) or more < 1 or more > MAX_QUEUED_WORK:
        raise ValueError("Invalid queued job count")
    if occupied_slots(db) + more > MAX_QUEUED_WORK:
        raise ValueError("Jarvis queue is full (50 waiting/running task slots); finish or cancel work first")
    return True


def may_start():
    """Yield to memory pressure when the *verified* 8 GiB slice is near throttle.

    Missing cgroup metrics in CI/unsupported environments are not interpreted
    as available RAM or as confirmation of enforcement. Production should
    verify the cgroup limit separately.
    """
    data = resources.snapshot()
    if not data.get("shared_cap_active"):
        return True
    used = data.get("used_bytes")
    high = data.get("throttle_above_bytes")
    if used is None:
        return True
    if high is None:
        high = 7 * 1024**3
    return used < max(0, high - MEMORY_HEADROOM_BYTES)


def snapshot(db):
    data = resources.snapshot()
    return {
        "queued_capacity": MAX_QUEUED_WORK,
        "occupied_slots": occupied_slots(db),
        "available_slots": max(0, MAX_QUEUED_WORK - occupied_slots(db)),
        "max_read_only_check_threads": MAX_CONCURRENT_READ_ONLY_CHECKS,
        "workers_are_processes": False,
        "memory_pressure_pauses_new_checks": not may_start(),
        "memory_slice_limit_active": bool(data.get("shared_cap_active")),
        "note": "50 is a total pending/running job limit, not 50 concurrent AI sessions. "
                "The real 8 GiB cgroup limit remains enforced by systemd.",
    }
