# ESN Jarvis / Personal AI

A secure, incremental ESN personal assistant for Pterodactyl Hosting, coding, business operations and panel improvements. This repository is **public**: never commit credentials, customer records, backups, private IPs, or production configuration.

## Verified scope of v0.1

- Owner-token authenticated HTTP API (loopback-only by default)
- Optional model-backed chat with persistent local SQLite conversation history
- Persistent audit trail of safe background jobs: panel health, node snapshots and server snapshots
- Pterodactyl **read-only** Application API calls (first page only; pagination returned)
- Explicit task allowlist; no ability to suspend, delete, restart, modify or provision customers
- No deployment to ESN nodes or panel yet

**Not implemented:** WhatsApp, Discord chat, multi-agent orchestration, autonomous browser, Stripe, GitHub writes, media rendering, voice, customer provisioning, panel redesign automation. See `docs/ROADMAP.md`.

## Setup (isolated host only)

Requires Python 3.11+ (Python 3.13 supported), no third-party packages.

1. Clone the repository to an isolated VPS or private dev environment. Do not run as root or on a Wings production host.
2. Configure the variables in `.env.example` as environment variables in your process manager. Use a cryptographically random token of at least 32 characters. **Never post tokens in chat.**
3. Use a restricted Pterodactyl **Application API** key with read permissions for nodes and servers, created at `https://panel.esnoffical.com/admin/api`. Leave blank to use chat only.
4. Run `python3 -m unittest discover -s tests -v`, then `python3 jarvis.py`.
5. Keep `ESN_BIND=127.0.0.1`. Access through Termius SSH port forwarding or a properly authenticated HTTPS reverse proxy; never expose plain HTTP directly to the public internet.

## Example from the same host

```bash
curl -H "Authorization: Bearer $ESN_OWNER_TOKEN" http://127.0.0.1:8765/api/status
curl -H "Authorization: Bearer $ESN_OWNER_TOKEN" -H 'Content-Type: application/json' -d '{"type":"nodes_snapshot"}' http://127.0.0.1:8765/api/jobs
curl -H "Authorization: Bearer $ESN_OWNER_TOKEN" http://127.0.0.1:8765/api/jobs
```

To chat, configure `OPENAI_API_KEY` and POST `{"message":"Hi Jarvis"}` to `/api/chat`. This sends your message and recent conversation context to the configured model provider. Do not include sensitive server/customer information.

**Security:** This is an owner-only prototype, not a hardened public service. SQLite history is stored unencrypted on disk; encrypt the volume and restrict filesystem permissions. Production requires TLS termination, rate limiting, monitoring, backups and more exhaustive verification. Never run AI-generated instructions directly on production infrastructure without explicit approval.

## v0.2 add-on: PIN-gated Connections dashboard and Discord bridge

- Mobile Connections interface at `/connections`; requires a six-digit PIN **and** a separate randomly generated owner token.
- Encrypted credential vault (`cryptography.Fernet`) for website logins and approved API tokens. Secrets cannot be retrieved through the dashboard API or sent to the language model.
- HttpOnly session cookie, 30-minute expiry, CSRF/origin protection, and failed-login throttling.
- Save, list and remove integrations; verify Discord bot token identity against the Discord API.
- Optional owner-only Discord slash commands (`/jarvis_status`, `/jarvis_ask`); bot access requires owner-provided Discord bot credentials and user ID.
- Added automated tests. No production server changes made.

**Setup on the isolated Jarvis VPS:**

```bash
python3 -m pip install -r requirements.txt
python3 -m connections generate-key   # store result privately as ESN_VAULT_KEY
python3 -m connections hash-pin       # enter PIN privately; store result as ESN_DASHBOARD_PIN_HASH
python3 -m unittest discover -s tests -v
python3 jarvis.py
```

The six-digit PIN given in chat is **not hardcoded**. Configure it via the interactive prompt above, and consider rotating it because chat content is not a private password manager. You must configure `ESN_OWNER_TOKEN` separately. Store the secrets in a protected systemd `EnvironmentFile` or other secret manager; **never commit real values to GitHub**. Back up the vault key securely because losing it makes credentials unrecoverable.

To use the optional Discord bot bridge, save a bot token as type `discord_bot` through the dashboard, then set `DISCORD_CONNECTION_ID` (the saved connection's ID), `DISCORD_OWNER_USER_ID`, and optionally `DISCORD_GUILD_ID` in the process environment. Install `discord.py` with `python3 -m pip install 'discord.py>=2.5,<3'`, then run `python3 discord_bridge.py` as a separate restricted service. You still must create/authorize the Discord application yourself in its Developer Portal. Never paste bot credentials into chat.

Use **HTTPS behind Nginx** with `ESN_PUBLIC_ORIGIN=https://jarvis.esnoffical.com`, `ESN_BIND=127.0.0.1`, and `ESN_COOKIE_SECURE=1`. No DNS or production deployment has been performed yet. See [Spaceship DNS & deployment](docs/DNS_AND_DEPLOY.md). The browser automation feature that could actually use stored website credentials is a later milestone.
