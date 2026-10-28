# ESN Jarvis: node storage, cleanup, coding, and integrations

## What ships now

- `/jarvis_disk` (owner-only, ephemeral Discord) checks **only the VPS running ESN Jarvis**.
- The authenticated `/tasks` Storage Audit panel gives current root-filesystem capacity and estimates the size of regular files older than seven days in `/opt/esn-jarvis/cache` and `/opt/esn-jarvis/tmp`, if those directories exist.
- `storage_audit` can be queued in the existing Task Center and included in owner-approved autonomous plans. Results are real, bounded, saved in the existing SQLite task database, and include a `remote_nodes_checked: 0` field.
- Audits use Python standard-library filesystem APIs, no shell or subprocess, no sudo, no elevated privileges, and **no file deletion**.
- Scanning never follows symlinked cache directories or symlinked children, and skips hard-linked files and separate mounts. The cache scan has entry, depth, and wall-time limits; truncated scans are labelled.
- No Pterodactyl customer files or metadata, backups, Docker layers, Wings secrets, or arbitrary paths are enumerated.

**Scope warning:** `shutil.disk_usage('/')` covers the filesystem mounted at `/` on the *current Jarvis VPS*. Its used/free numbers can include customer storage hosted on that same volume, but the report does not inspect or identify those files. It is not a report of all four ESN nodes.

## Customer data that is explicitly protected

Pterodactyl Wings may store files under these paths by default (check the actual `/etc/pterodactyl/config.yml` for custom locations):

- `/var/lib/pterodactyl/volumes`: live customer server files
- `/var/lib/pterodactyl/backups`: local customer backups
- `/var/lib/pterodactyl/archives`: server transfer archives
- `/etc/pterodactyl`: Wings configuration and credentials
- `/var/lib/docker`: running container storage

No Jarvis tool may delete or alter those trees simply to reclaim disk space. Never use blanket `rm -rf`, `docker system prune --volumes`, or directory-wide cleanups on shared production nodes.

## Next: real remote node diagnostics

Deploy a *separate least-privilege, host-bound read-only agent* on each approved Wings VPS:

1. Explicitly register the server identity and verify a unique mutual-auth credential.
2. Collect storage health, disk pressure, mounts, and limited service metadata without reading customer files or secrets.
3. Use outbound-only or VPN/TLS authenticated transport; isolate host permissions; enforce timeouts and rate limits.
4. Only then show four independent node reports in Jarvis. A Pterodactyl node-list API response does **not** prove real free disk space on the underlying host.
5. Audit access and allow disconnection/revocation independently for each node.

## Next: safe, **approval-gated** cleanup

1. Run a dry-run scan that labels candidate files with actual ownership, age, size, service impact and reason.
2. Exclude customer files, Wings backups, Docker volumes, Pterodactyl panel database, active logs, required caches, and running processes by default.
3. Require a fresh, explicit owner approval for a specific action and node; avoid one sweeping approval for unrelated removals.
4. Before changing files, verify their identities and owner, create backups where relevant and protect against symlink/path swaps. Use narrow built-in maintenance functions rather than arbitrary shell commands.
5. Prefer reversible quarantine with expiration to permanent deletion, with a clear rollback and before/after disk measurement.
6. Never automatically delete a customer's game world, backup or server files even when storage is low.

## Next: coding and self-optimization, realistically

Jarvis can become a *reviewable coding agent*, not an infallible unlimited programmer:

- Secure GitHub integration with per-repository scopes and rotating credentials stored only in the encrypted Connections vault.
- Work on a new Git branch or isolated workspace, apply patches, run tests/lint, produce a diff and optional preview.
- Submit pull requests and ask for approval before merge or production deployment. Never modify its own running source directly.
- For self-optimization, measure CPU/RAM/performance, propose small controlled changes, benchmark and automatically roll back failed deployments.
- Keep `esnjarvis.slice` with the shared 8 GiB RAM and two-core CPU ceilings. Video rendering or heavy compilation must use a separate worker so Wings and customer services remain protected.
- Code quality still depends on the underlying local Qwen3 model, tests, and tooling; self-modification alone will not make a 1.7B model an expert in every language.

## Next: panel redesign and connections

- First identify the installed Pterodactyl version and theme/extension mechanism, and review the screenshots the owner supplies. Draft UI changes in a *staging clone*, not on the production panel. Review both desktop/mobile, routing, permissions, server management, and rollback before owner approval.
- Introduce individual connectors for services such as GitHub, Spaceship DNS, Pterodactyl, Stripe and design apps. Each has specific OAuth/API permissions and revocation. “Connect to anything” cannot mean blanket access to arbitrary websites or accounts.
- Keep human-in-the-loop verification for CAPTCHA, MFA and WebAuthn. Do not bypass website security measures.

## Installation after GitHub tests pass

Pull `main`, run the existing full test suite, and restart only `esn-jarvis` and `esn-jarvis-discord`. The storage reporter uses only the Python standard library and does not change systemd permissions, start a new root daemon or restart Wings, Docker, Nginx or customer servers. The existing 8 GiB cgroup remains unchanged.

**Start with:** `/jarvis_disk` in Discord or the new **Storage Audit** panel at `https://jarvis.esnoffical.com/tasks`. Send the usage numbers and node-specific screenshots before authorizing any cleanup design.
