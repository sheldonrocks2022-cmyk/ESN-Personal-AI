# Step 57 — Jarvis power mode (reversible and customer-safe)

## Current VPS findings

User-reported Termius output: \`/dev/vda1\` ext4 filesystem, about **90 GiB total**, **36 GiB used**, **54 GiB available** as measured with \`df -h /opt/esn-jarvis\`. That is free storage on the **existing filesystem**, not a new extra disk or a dedicated Jarvis 5 GiB partition. Jarvis can use free filesystem space without changing the VPS bill; reserving 5 GiB specifically would be a distinct disk-quota project.

The existing \`esnjarvis.slice\` sets a **maximum** of 8 GiB shared RAM across \`ollama.service\`, \`esn-jarvis.service\`, and \`esn-jarvis-discord.service\`. It does **not** pre-allocate 8 GiB. Turning off Jarvis releases the RAM and CPU it is *actually using* at shutdown time. Turning it off does **not** free disk space occupied by its Ollama models, caches, app code, databases, or service files. Any disk reclaim is separately planned and individually approved.

**Scope:** This functionality is designed for the VPS where Jarvis runs. Whether reclaimed CPU/RAM can serve customer servers depends on whether those servers run on this same VPS and whether Pterodactyl node allocations are configured to permit them. It does not transfer capacity to other ESN nodes.

## Install once from Termius as root

Pull the merged code first, then preview:

\`\`\`sh
python3 /opt/esn-jarvis/app/scripts/install_power_command.py
\`\`\`

Install only the fixed command wrapper (does not start/stop any service):

\`\`\`sh
python3 /opt/esn-jarvis/app/scripts/install_power_command.py --apply
\`\`\`

The wrapper is \`/usr/local/sbin/esnjarvis\`. It runs the checked-out \`/opt/esn-jarvis/app/scripts/jarvis_power.py\` using the system Python. This code requires no third-party Python packages.

## One-command controls

\`\`\`sh
esnjarvis status
esnjarvis off
esnjarvis on
\`\`\`

- \`status\`: read-only status of Jarvis web, Discord, Ollama, current host disk-free and available host RAM.
- \`off\`: **stop and disable** the Jarvis Discord service, Jarvis web/API, and (only if it belongs to \`esnjarvis.slice\`) the Ollama server. It persists original enable states in a root-owned mode-0600 snapshot so a reboot does not automatically bring Jarvis back. After OFF, Jarvis's web dashboard and Discord bot will be unreachable until turned back ON.
- \`on\`: restores the original boot-enable states and starts the previously stopped units in dependency order (Ollama → web → Discord). It retains the recovery snapshot if a start fails, allowing a safe retry. Wait a few seconds after service start before checking web readiness.
- \`off --dry-run\`: preview what would stop **without changes**.
- \`off --keep-ollama\`: stop web and Discord only if Ollama is **shared by other apps**. This does NOT power down Ollama or free its inference RAM.
- \`on --dry-run\`: preview restoration.

**Do not run \`esnjarvis off\` from an unsaved Jarvis chat session.** You will lose the browser/Discord connection when you stop it. Keep a working root SSH connection through Termius or provider rescue console so you can issue \`esnjarvis on\`. Never shut off Wings/Docker to gain Jarvis RAM.

### Protections

- Exactly three hardcoded service units (two when \`--keep-ollama\` is specified). No user-provided unit names, shell expansion, arbitrary system commands, or credential handling.
- **Never** stops or disables \`wings.service\`, \`docker.service\`, \`nginx.service\`, \`pteroq.service\`, \`mariadb.service\`, ESN customer game servers, panel allocations, backups, DNS, Stripe, or any connected external service.
- Ollama is stopped only if its \`Slice\` is \`esnjarvis.slice\`; otherwise the command explicitly refuses and suggests keeping Ollama running.
- Root required for changes; the state file is mode \`0600\` in a root-owned \`0700\` directory.
- Saves original enabled/disabled/static/indirect state before any stop, and never silently resets original settings on repeat OFF.
- Uses a file lock to prevent concurrent on/off changes.
- Provides explicit state and status output; no media files, customer server worlds, backups, AI model blobs or other data are deleted.
- \`systemctl disable --now\` prevents boot-time auto-start but cannot prevent a separate administrator or external dependency from explicitly starting the service. The script verifies stopped state afterward and reports an error if the service starts again.
- A shell or VPS power outage midway through a transition may leave some Jarvis units off; the saved snapshot allows retry without affecting customers.

## Resource verification

Before and after OFF:

\`\`\`sh
esnjarvis status
free -h
df -h /opt/esn-jarvis
\`\`\`

\`free -h\` compares host-wide memory availability, which can fluctuate as Linux caches and customer processes work. \`df -h\` should normally show the same free disk after OFF because nothing was deleted.

For the next phase, a separately approved read-only storage audit can identify Jarvis-owned unused media/cache or voluntarily removable Ollama models for **real disk reclaim**, but must not delete customer storage or secret files by default.

## Troubleshooting

- If OFF refuses with an Ollama shared-slice message: use \`esnjarvis off --keep-ollama\`, or inspect \`systemctl show ollama -p Slice\` and existing dependent apps.
- If status shows Jarvis still active after OFF: check \`systemctl status esn-jarvis esn-jarvis-discord ollama --no-pager\`; do not force-stop unknown containers.
- If ON reports startup failure, examine \`journalctl -u esn-jarvis -n 30 --no-pager\` and retry \`esnjarvis on\` once fixed.
- After ON: \`curl -fsS --retry 3 --retry-delay 2 --retry-connrefused http://127.0.0.1:8765/health\`.
- To uninstall only the convenience wrapper, remove \`/usr/local/sbin/esnjarvis\` **after** restoring Jarvis ON; leave all unit files and service installations unchanged.

This power switch does not automatically toggle ChatGPT-hosted ESN checks or automations outside the Jarvis VPS.
