#!/usr/bin/env python3
"""Remove ONLY the ESN Jarvis deployment from this VPS.

Single command after the reviewed code is deployed:
  python3 /opt/esn-jarvis/app/scripts/uninstall_jarvis.py --apply

No customer services, Pterodactyl nodes, Wings, Docker, other ESN nodes,
system Ollama installations/models, DNS, or GitHub repositories are deleted.
This command PERMANENTLY deletes Jarvis's local credentials, data and files.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

APP = Path("/opt/esn-jarvis")
SERVICE_DIR = Path("/etc/systemd/system")
WEB_UNIT = SERVICE_DIR / "esn-jarvis.service"
DISCORD_UNIT = SERVICE_DIR / "esn-jarvis-discord.service"
SERVICES = ("esn-jarvis-discord.service", "esn-jarvis.service")
POWER_COMMAND = Path("/usr/local/sbin/esnjarvis")
PRIVATE_ENV = Path("/etc/esn-jarvis.env")
CAPACITY_CONFIG = Path("/etc/esn-jarvis-customer-capacity.json")
POWER_STATE = Path("/var/lib/esn-jarvis-power")
NGINX_AVAILABLE = Path("/etc/nginx/sites-available/esn-jarvis")
NGINX_ENABLED = Path("/etc/nginx/sites-enabled/esn-jarvis")
NGINX_ACME = Path("/var/www/esn-jarvis-acme")
DEDICATED_BUDGETS = (
    SERVICE_DIR / "esn-jarvis.service.d/90-esn-budget.conf",
    SERVICE_DIR / "esn-jarvis-discord.service.d/90-esn-budget.conf",
)
POWER_WRAPPER_MARKER = "/opt/esn-jarvis/app/scripts/jarvis_power.py"
LIMITED_UNIT_MARKER = "/opt/esn-jarvis/"
JARVIS_HOST = "jarvis.esnoffical.com"
BACKUP = NGINX_AVAILABLE.parent / ".esn-jarvis-uninstall-tmp"
REMOVED = []


def run(*args):
    try:
        result = subprocess.run(args, text=True, capture_output=True,
                                timeout=35, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Unable to execute local maintenance program") from exc
    if result.returncode != 0:
        # Avoid emitting systemctl/unit stderr, which may contain env values.
        raise RuntimeError("Command failed: " + " ".join(args[:2]))
    return result.stdout.strip()


def safe_path(path):
    """Never follow a planted symlink, including exact Jarvis paths."""
    p = Path(path)
    if p.is_symlink():
        raise RuntimeError("Refusing symlinked Jarvis path: " + str(p))
    return p


def safe_text(path, marker):
    p = safe_path(path)
    if not p.exists():
        return None
    if not p.is_file():
        raise RuntimeError("Expected Jarvis file but found another object: " + str(p))
    data = p.read_text(encoding="utf-8")
    if marker not in data:
        raise RuntimeError("Unexpected content; refusing to delete: " + str(p))
    return data


def guard_nested_mounts(root):
    """Don't delete a customer volume mounted below the Jarvis tree."""
    root = safe_path(root)
    if not root.exists():
        return
    if not root.is_dir() or os.path.ismount(root):
        raise RuntimeError("Jarvis path is not an ordinary directory: " + str(root))
    # /proc/self/mountinfo uses octal escapes for mount paths.
    mounts = Path("/proc/self/mountinfo").read_text().splitlines()
    prefix = str(root) + "/"
    for line in mounts:
        parts = line.split()
        if len(parts) < 5:
            raise RuntimeError("Invalid mount table; refusing recursive deletion")
        name = re.sub(r"\\([0-7]{3})",
                      lambda m: chr(int(m.group(1), 8)), parts[4])
        if name == str(root) or name.startswith(prefix):
            raise RuntimeError("Mounted filesystem under Jarvis path: " + name)


def plan():
    if os.geteuid() != 0:
        raise RuntimeError("Run as root through Termius")
    if safe_path(CAPACITY_CONFIG).exists():
        raise RuntimeError(
            "Customer-first RAM switching is configured. Refusing to orphan "
            "Node 1 policy. Run 'esnjarvis customers disable' while Jarvis "
            "is ON and the node is at its original memory baseline, then retry."
        )
    power_data = POWER_STATE / "last-off.json"
    if safe_path(power_data).exists():
        try:
            state = json.loads(power_data.read_text())
        except (ValueError, OSError):
            raise RuntimeError("Unrecognized power recovery record; refusing removal") from None
        if "capacity" in state:
            raise RuntimeError(
                "A Jarvis OFF record contains customer RAM switching. "
                "Refusing to remove the panel-recovery configuration."
            )
    guard_nested_mounts(APP)
    guard_nested_mounts(POWER_STATE)
    guard_nested_mounts(NGINX_ACME)
    if not (APP / "app" / "jarvis.py").is_file():
        raise RuntimeError("Expected Jarvis installation not found at /opt/esn-jarvis")
    for unit in (WEB_UNIT, DISCORD_UNIT):
        safe_text(unit, LIMITED_UNIT_MARKER)
    safe_text(POWER_COMMAND, POWER_WRAPPER_MARKER)
    for path in DEDICATED_BUDGETS:
        safe_text(path, "Slice=esnjarvis.slice")
    safe_path(PRIVATE_ENV)
    if PRIVATE_ENV.exists() and not PRIVATE_ENV.is_file():
        raise RuntimeError("Unexpected Jarvis environment file")
    if safe_path(BACKUP).exists():
        raise RuntimeError("A pending Nginx uninstall backup already exists; refusing changes")
    conf = safe_text(NGINX_AVAILABLE, JARVIS_HOST)
    if conf is not None:
        names = re.findall(r"(?m)^\s*server_name\s+([^;]+);", conf)
        if not names or any(name.strip() != JARVIS_HOST for name in names):
            raise RuntimeError("Jarvis Nginx site contains another hostname; refusing deletion")
    if NGINX_ENABLED.exists() or NGINX_ENABLED.is_symlink():
        if not NGINX_ENABLED.is_symlink() or NGINX_ENABLED.resolve() != NGINX_AVAILABLE:
            raise RuntimeError("Jarvis Nginx enabled path is not the expected site link")
    print("JARVIS-ONLY UNINSTALL VERIFIED")
    print("WILL permanently remove Jarvis app, local vault, secrets and task data.")
    print("WILL stop/disable dedicated Jarvis web and Discord services.")
    print("WILL remove Jarvis-only Nginx site and reload Nginx without stopping it.")
    print("WILL remove Jarvis-only systemd units, controls and power state.")
    print("WILL NOT touch Wings, Docker, Pterodactyl, other nodes, customer servers, or Node 1 memory limit.")
    print("WILL NOT uninstall system-wide Ollama, its models, ESN DNS, the certbot certificate or GitHub repo.")
    return conf is not None


def remove_nginx():
    if not NGINX_AVAILABLE.exists() and not NGINX_ENABLED.is_symlink():
        return
    # Preserve site config until reload and test both succeed.
    had_link = NGINX_ENABLED.is_symlink()
    if had_link:
        NGINX_ENABLED.unlink()
    NGINX_AVAILABLE.rename(BACKUP)
    try:
        run("nginx", "-t")
        run("systemctl", "reload", "nginx")
    except Exception:
        BACKUP.rename(NGINX_AVAILABLE)
        if had_link:
            NGINX_ENABLED.symlink_to(NGINX_AVAILABLE)
        raise
    BACKUP.unlink()
    REMOVED.append(str(NGINX_AVAILABLE))


def delete_file(path):
    path = safe_path(path)
    if path.exists():
        if not path.is_file():
            raise RuntimeError("Refusing unexpected file type: " + str(path))
        path.unlink()
        REMOVED.append(str(path))


def delete_tree(path):
    path = safe_path(path)
    if path.exists():
        guard_nested_mounts(path)
        shutil.rmtree(path)
        REMOVED.append(str(path))


def apply():
    have_nginx = plan()
    print("Removing ONLY Jarvis now (data deletion is irreversible).")
    for service in SERVICES:
        run("systemctl", "disable", "--now", service)
        print("Stopped and disabled " + service)
    if have_nginx:
        remove_nginx()
        print("Removed Jarvis Nginx site; other sites remain enabled.")
    for path in (WEB_UNIT, DISCORD_UNIT, *DEDICATED_BUDGETS):
        delete_file(path)
    for directory in (SERVICE_DIR / "esn-jarvis.service.d",
                      SERVICE_DIR / "esn-jarvis-discord.service.d"):
        if directory.is_dir() and not directory.is_symlink():
            try:
                directory.rmdir()  # only if empty; preserve unrelated drop-ins
            except OSError:
                pass
    run("systemctl", "daemon-reload")
    # Generic system-wide Ollama may serve other services. Deliberately do
    # not touch ollama.service, its 90-esn-budget.conf, or its slice while active.
    delete_file(POWER_COMMAND)
    delete_file(PRIVATE_ENV)
    delete_tree(POWER_STATE)
    delete_tree(NGINX_ACME)
    delete_tree(APP)  # the script's bytes are already in Python memory
    print("SUCCESS: ESN Jarvis local services, app, secrets and files removed.")
    print("Unchanged: Wings/Pterodactyl/customer servers/Node 1 RAM limit.")
    print("Preserved for safety: system Ollama and shared-resource override, "
          "TLS certificate, DNS, GitHub repo, external credentials.")
    print("Revoke Jarvis-specific Discord and Pterodactyl tokens separately.")
    print("The old customer node memory allowance remains unchanged (last reported 11264 MiB).")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true",
                   help="permanently remove Jarvis-only local installation")
    args = p.parse_args()
    try:
        if args.apply:
            apply()
        else:
            plan()
            print("PREVIEW ONLY — no files deleted. Add --apply to uninstall.")
    except (RuntimeError, OSError, ValueError, UnicodeError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
