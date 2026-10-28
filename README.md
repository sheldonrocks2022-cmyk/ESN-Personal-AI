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


## v0.5: PIN-gated assistant with verified tasks

The private `/assistant` page integrates an optional model-backed chat with the v0.4 read-only Task Center. It can request a **real queued check**, return a real job ID, and never claim completion before the job finishes. Every model tool call is validated against a strict allowlist. It cannot run arbitrary code, access vault secrets, alter DNS, charge customers, or bypass human verification. The dashboard shares the existing PIN + independent owner-token access session. See [Chat-to-tools documentation](docs/CHAT_TOOLS.md).

## Local AI brain (optional)

Jarvis supports `ESN_AI_PROVIDER=ollama` for local-only model inference at `127.0.0.1:11434`; website `/assistant` and Discord `/jarvis_ask` use the same `jarvis.chat` function and its restricted tool allowlist. Default remains `openai` until explicitly switched. Set `OLLAMA_MODEL=qwen3:1.7b` and download that model using Ollama. No OpenAI API key is required in local mode. The server does not install Ollama automatically.

**Shared Wings host warning:** This machine also serves customer workloads. Limit Ollama with a dedicated non-root systemd service (`CPUQuota`, `MemoryMax`, `TasksMax`), no public Ollama port, one inference at a time, short context, and idle model eviction. Start with the 1.7B 4-bit model, not 7B+, then measure customer latency. This adapter is code-only until deployed, running, and integration-tested; a live model is not currently verified.

## Optional 8 GiB shared Jarvis budget

To place Ollama, Jarvis web and Jarvis Discord under one real cgroup RAM ceiling (without touching Wings), see [8 GiB systemd budget setup](docs/RESOURCE_BUDGET_8GB.md). A safe preview script is included; no host configuration is changed by GitHub updates alone. The owner-authenticated Task Center shows verified slice usage after activation.

## Step 53: owner-approved autonomous tasks

Jarvis supports a durable, **read-only** multi-step workflow engine. Create an audit in the owner-only Discord bot with `/jarvis_auto goal:Audit ESN panel, website and GitHub`, review its steps, approve the plan using `/jarvis_auto_approve`, then query `/jarvis_auto_status` or the authenticated `/tasks` dashboard for actual completed results. You may cancel remaining work with `/jarvis_auto_cancel`. A saved plan never runs without approval. The fixed allowlist blocks shell commands, payments, DNS changes, destructive actions, deployments, or arbitrary websites. See [Step 53 guide](docs/STEP53_AUTONOMOUS.md). This is a limited workflow engine, not a general-purpose self-directed software operator.

## Node storage diagnostics (safe first phase)

Use owner-only Discord `/jarvis_disk`, the `/tasks` Storage Audit panel or the `storage_audit` read-only task to see disk utilization and *estimates* for aged Jarvis-owned temporary files on the VPS where Jarvis runs. No deletion, root access, arbitrary paths, remote-node scanning or customer storage reads are added. Follow the [Node Maintenance Roadmap](docs/NODE_MAINTENANCE.md) for separate authenticated agent rollout and approval-gated cleanup. The shared 8 GiB Jarvis limit remains unchanged.

## Private Discord DMs and Command Center

Owner-to-bot DMs now accept ordinary text using the configured local Jarvis model. Unrecognized senders receive `This bot is private`. The owner may create time-limited, quota-limited **chat-only** guest grants through `/jarvis_dm_grant`, inspect them with `/jarvis_dm_guests` and revoke with `/jarvis_dm_revoke`. Guest chats are isolated from owner notes, tools, secrets and history. A new authenticated `/dashboard` displays live metrics and navigation, with responsive styling throughout the site. See [Private DMs and Command Center](docs/PRIVATE_DM_AND_DASHBOARD.md). No automatic access to your personal Discord DMs, YouTube uploads, or new Discord guild creation is included.

## Step 55 — DM command access, search and 50-slot budget

All owner commands can be accessed in a bot DM using slash commands (explicit global BOT_DM context) or the text fallback `!jarvis help`. New read-only panel node/server inventory commands and optionally configured Brave Search API commands are provided. A combined 50 **queued job** budget and memory-pressure guard keep actual execution constrained to the existing small worker loops and the shared 8 GiB systemd slice. No Discord user self-bot, token harvesting, remote node cleanup or panel mutations. [Read deployment guide](docs/STEP55_DM_WORKERS_RESEARCH.md).
