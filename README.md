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

## v0.3 Creative Studio foundation (opt-in)

This revision adds a **real local video editor** and vector logo creator, without requiring an AI image/video generator. These are rule-based creative tools under the owner's control.

- Install **FFmpeg + FFprobe** on a separate creative worker. Set `ESN_CREATIVE_ENABLED=1` and an isolated `ESN_MEDIA_ROOT` path in the process environment (default disabled). Ensure the service account owns the directory and doesn't have access to Pterodactyl/Wings or customer files.
- For optional PNG logo export, install `cairosvg>=2.8,<3` and its system Cairo libraries. SVG generation works without CairoSVG.
- Place authorized `.mp4`, `.mov`, `.mkv`, `.webm`, `.m4v`, and permitted audio files in `$ESN_MEDIA_ROOT/inputs` via SFTP. Filename must contain letters/digits/dots/dashes/underscores only. No remote URLs are accepted by the render API.
- Visit `https://jarvis.esnoffical.com/connections` and sign in with your PIN + owner token. Open `/studio` on the same origin to render edits and logos, check real job status, and download artifacts. You may also call `/api/studio/assets`, `/api/studio/render`, `/api/studio/logo`, `/api/studio/jobs` with the existing owner Bearer token.
- The first renderer supports clip trims, aspect-ratio crops, titles, several color looks, separate provided soundtrack, up to 8 clips / 60 seconds, 24/30/60 FPS, and export sizes up to 1080×1920 or 1920×1080. It produces real H.264 MP4 files in `$ESN_MEDIA_ROOT/exports` (not AI-generated). Original clip audio is not retained in this first version unless separately provided as soundtrack.
- A handoff ZIP contains an editable shot-list JSON and an **After Effects ExtendScript JSX** project-assembly script. Run the JSX in a licensed After Effects installation on Windows/macOS after copying your original source files into an `inputs` folder beside the JSX file. CapCut has no generally supported public automation API: manually import the media using the shot list. No deceptive claim of CapCut headless rendering.
- Logo generator creates real editable SVG, optionally PNG. Three symbol styles and configurable color scheme. It is intentionally simple: advanced vector design, typography, compositing and live desktop integration are later steps.
- Media editing needs appropriate rights for clips and soundtracks. All media is stored outside Git. Owner approval required for uploading/publishing content.

**Deployment/security limits:** this is a controlled prototype, not a production-ready public video hosting service. The one-process thread queue isn't restart-durable; jobs interrupted during a restart must be resubmitted. Put a strong HTTPS/authenticating gateway in front of it, restrict studio users to the owner, set worker CPU/disk limits, and monitor output disk growth. Rendering is disabled by default. Do not host on production ESN nodes.


## v0.4: Persistent Task Center

The owner-only **/tasks** interface uses the existing PIN + owner-token session. It provides a durable SQLite job queue, real results, safe read-only checks of ESN Website, public GitHub repository, Pterodactyl panel/nodes/servers, recurring schedules (15 minutes to daily), bounded retries, cancellation of queued jobs, and a public-page browser inspector (optional Playwright). Jobs and schedules remain recorded after restarts.

Creative Studio rendering/logo operations are queued persistently and recover pending tasks after service restarts; intensive media rendering still requires an isolated media worker. Nothing here changes customer servers, Stripe, Discord administration, DNS, or production configuration. Read [deployment guide](docs/DEPLOY_V04.md) and [the task implementation](operations.py). Do not deploy this feature branch without reviewing the configuration and verifying HTTPS.

This is still an incremental prototype; unrestricted desktop agents, authenticated browsing, official passkey management, advanced CapCut/After Effects control, and broad write-permission actions are **not built**.
