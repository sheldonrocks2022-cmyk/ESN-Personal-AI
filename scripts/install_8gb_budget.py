#!/usr/bin/env python3
"""Preview/install an 8 GiB shared systemd slice for three ESN Jarvis services.

Default is READ ONLY. --apply writes only new ESN-namespaced drop-ins, calls
systemctl daemon-reload, and deliberately DOES NOT restart running services.
Existing nonmatching budget config files are never overwritten.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys

SERVICES = ("esn-jarvis.service", "esn-jarvis-discord.service", "ollama.service")
ROOT = Path("/etc/systemd/system")
SLICE = """[Unit]
Description=ESN Jarvis shared resource budget (not Wings)

[Slice]
MemoryAccounting=yes
MemoryHigh=7G
MemoryMax=8G
CPUAccounting=yes
CPUQuota=200%
"""
OVERRIDE = """[Service]
Slice=esnjarvis.slice
"""


def manifest(root=ROOT):
    files = {root / "esnjarvis.slice": SLICE}
    for unit in SERVICES:
        files[root / (unit + ".d") / "90-esn-budget.conf"] = OVERRIDE
    return files


def preflight(files):
    """Reject conflicting files before any modifications."""
    for path, contents in files.items():
        if path.exists():
            if not path.is_file() or path.is_symlink() or path.read_text() != contents:
                raise RuntimeError(f"Refusing to overwrite existing file: {path}")


def apply(files, runner=subprocess.run):
    if os.geteuid() != 0:
        raise RuntimeError("--apply requires root")
    # No surprise changes to Pterodactyl or other services.
    for unit in SERVICES:
        runner(["systemctl", "cat", unit], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    preflight(files)
    for path, contents in files.items():
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create prevents clobbering between preflight and write.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "w") as output:
            output.write(contents)
    runner(["systemctl", "daemon-reload"], check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true", help="write ESN budget files; requires root; no service restarts")
    args = p.parse_args()
    files = manifest()
    try:
        preflight(files)
        if args.apply:
            apply(files)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("ESN shared resource budget: MemoryHigh=7G, MemoryMax=8G, CPUQuota=200%")
    for path in files:
        print(("Installed: " if args.apply else "Plan: ") + str(path))
    if args.apply:
        print("Drop-ins installed, but not yet active for running processes.")
        print("After checking maintenance impact, restart ONLY: systemctl restart ollama esn-jarvis esn-jarvis-discord")
        print("Then verify: systemctl show ollama esn-jarvis esn-jarvis-discord -p Slice")
        print("And inspect: systemctl show esnjarvis.slice -p MemoryMax -p MemoryHigh")
    else:
        print("DRY RUN ONLY; nothing changed. To install, rerun with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
