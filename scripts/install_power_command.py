#!/usr/bin/env python3
"""Install a fixed root-only Jarvis power command; default is a read-only preview.

The wrapper points at the checked-out script, so future Git updates are picked
up without replacing the installed command. Existing unrelated files are not
overwritten.
"""
import argparse
import os
from pathlib import Path
import sys

COMMAND = Path("/usr/local/sbin/esnjarvis")
WRAPPER = (
    "#!/bin/sh\n"
    "exec /usr/bin/python3 /opt/esn-jarvis/app/scripts/jarvis_power.py \"$@\"\n"
)


def install(path=COMMAND, *, apply=False):
    if path.is_symlink():
        raise RuntimeError("Refusing existing symlink at " + str(path))
    if path.exists():
        if not path.is_file() or path.read_text(encoding="utf-8") != WRAPPER:
            raise RuntimeError("Refusing to overwrite pre-existing command at " + str(path))
        if apply:
            print("Jarvis power command already installed; no changes needed.")
        else:
            print("Existing Jarvis power command matches expected wrapper.")
        return
    print("Jarvis power command target: " + str(path))
    print("Executes fixed, root-only /opt/esn-jarvis/app/scripts/jarvis_power.py")
    if not apply:
        print("DRY RUN ONLY. Nothing installed. Use --apply when ready.")
        return
    if os.geteuid() != 0:
        raise RuntimeError("Installation requires root (Termius)")
    # Never touch existing files; create only our own command.
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o755)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(WRAPPER)
        path.chmod(0o755)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    print("Installed. Commands: esnjarvis status | esnjarvis off | esnjarvis on")
    print("Optional: esnjarvis off --keep-ollama (if Ollama serves other apps)")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true", help="install command with permission checks")
    args = p.parse_args(argv)
    try:
        install(apply=args.apply)
    except (RuntimeError, OSError, UnicodeError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
