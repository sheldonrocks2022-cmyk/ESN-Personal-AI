# ESN Jarvis master roadmap

## Ground rules
- Preserve the four existing ESN nodes, customer servers, Wings, Pterodactyl database, allocations, Stripe integrations and working ESN services.
- Explicit owner approval for payments/refunds, DNS changes, server deletions, migrations, public deployments and risky work.
- Real workers, real task IDs, logs, tests and honest completion reporting. No fake execution claims.
- Never commit secrets or customer details to this public repository; stage changes off production.

## Staged milestones
1. **v0.1**: Owner-only HTTP API, optional model chat with SQLite memory, persistent job logs and read-only Pterodactyl monitoring.
2. **v0.2**: Authenticated mobile dashboard, Discord bot bridge, reliable scheduled polling and notifications.
3. **v0.3**: Durable workers, real multi-agent orchestration, cancellation, task approval and model/provider routing.
4. **v0.4**: GitHub branch/PR coding workers, restricted staging shell, browser automation, document tools and screenshots.
5. **v0.5**: Approved Pterodactyl provisioning, trials/subscriptions, ESN Guardian and customer support tools.
6. **v0.6**: Stripe, ESN website, Minecraft SMP, marketing and media integrations.
7. **v0.7**: WhatsApp provider, voice in/out, calling, rich personal assistant features.
8. **Panel design**: inspect installed Pterodactyl frontend and screenshots, stage/test premium responsive theme, deploy only with approval.

Milestones are goals, not completed features. Each requires testing and evidence.

## Cinematic media and authorized login automation
- **Media studio (planned):** ingest authorized reference footage; cinematic editing pipeline with beat/scene analysis, speed ramps, compositing, motion graphics, isolated rendering workers, 4K/vertical exports, previews, revisions, and real downloadable video artifacts.
- **Passkeys (planned):** support site-approved WebAuthn passkey registration with owner approval and secure authenticator custody, not LLM-held keys. No passkeys are currently provisioned.
- **Human checks:** pause for legitimate CAPTCHA/MFA/identity verification and hand the browser session back to the owner. Do not bypass anti-bot or identity protections.
- **Safety:** keep media rendering separate from Pterodactyl production nodes; no automatic posting or paid API use without permission.
- Detailed specification and acceptance tests: [Cinematic Media Studio and Authorized Authentication](MEDIA_AND_AUTH.md).


## v0.4 progress: real task center

- Implemented durable, bounded read-only operations in `operations.py`: verified results, recurring checks, failure auditing, browser inspector restricted to public ESN domains, and queued-job cancellation.
- Implemented mobile `/tasks` dashboard using the v0.2 PIN + owner-token authenticated session.
- Media queue persists real edit/logo work plans across service restarts (one renderer per isolated worker).
- New automated tests validate persistence, cancellation, scheduling, retry limits and restrictions; local suite passed 22 tests.
- Available for review on a development branch; **not deployed**. See [deploy checklist](DEPLOY_V04.md).
- Remaining: secure owner-approved write actions, desktop/After Effects/CapCut control adapters, multi-agent orchestration, more advanced cinematic effects, WebAuthn passkeys, human-auth handoffs, and integrated business workflows.


## v0.5 safe agent bridge

- Added owner-session-gated `/assistant` chat dashboard with model function calling.
- Model can ask for up to 3 read-only tasks, subject to independent server-side allowlist validation, and receives genuine job IDs. No shell, account mutation, or financial tools.
- Added safeguards for credentials in messages and per-request CSRF checks. AI provider key is optional and server-side.
- 28 local automated tests passed including gating, tool allowlist and mocked provider response.
- Live deployment and credentials are not configured by this code push. See [Chat tools](CHAT_TOOLS.md).

## Shared 8 GiB deployment ceiling

- Optional parent systemd slice with MemoryHigh=7G and MemoryMax=8G across Ollama, Jarvis web, and Discord; preserves existing tighter individual caps.
- Read-only live cgroup usage indicator in Task Center; no claim of an active cap until actually applied and services restarted into slice.
- See [8 GiB resource budget](RESOURCE_BUDGET_8GB.md). AI capability expansion is separate, staged, and never guaranteed by raising model memory.

## Step 53: owner-approved autonomous read-only workflow engine

- Added persistent multi-step plans stored in SQLite and executed sequentially by a bounded background worker after explicit owner approval.
- Safe goal parser supports health checks of ESN panel, public website, GitHub, nodes and servers. Invalid/destructive requests are rejected rather than partially executed. Browser scans, shell, API writes, DNS, Stripe, customer changes, and arbitrary URLs are excluded.
- Owner-only Discord `/jarvis_auto`, `/jarvis_auto_approve`, `/jarvis_auto_status`, `/jarvis_auto_cancel`; Task Center includes preview, approval, cancellation, progress and verified per-step results.
- One read-only step at a time; persistent retry-once and crash lease recovery, bounded plan length (five checks) and active plan count (eight); cooperative cancellation. No uncontrolled model-generated commands.
- This is a guarded orchestration foundation, **not** unconstrained computer use or permission to alter production systems. Jarvis and Ollama stay in the existing shared 8 GiB slice.

## Storage maintenance and advanced capability roadmap

- **Implemented read-only:** local Jarvis VPS filesystem capacity audit, bounded aged Jarvis-owned temporary/cache estimates, owner-only Discord `/jarvis_disk`, Task Center display, and auditable `storage_audit` jobs. No cleanup or remote node access is implied.
- **Next:** isolated, authenticated read-only agents on each Wings node; explicit node inventory and disk pressure monitoring. Never read customer server contents by default.
- **Next:** dry-run maintenance proposals with exact file sets, ownership checks, backups, per-action owner approval, server-aware locks and recovery. No automatic deletion of Pterodactyl volumes/backups/archives or Docker data.
- **Next:** least-privilege Github coding adapters: stage changes on branches, run CI, review diffs, require explicit approval before deployments or self-modification; benchmark and rollback with the 8 GiB cap.
- **Next:** connector registry for supported services (OAuth/API permissions, vault encryption, scope and revocation), and separately staged Pterodactyl front-end designs after screenshots and version checks. Nothing connects to arbitrary services automatically.

## Private DM bridge and Command Center V2

- New owner-only direct text messages to the ESN Jarvis bot and time-limited chat-only guest grants with expiration, strict message quotas, revocation, and owner-only slash commands. Unapproved DM senders get `This bot is private`; no guild text monitoring or self-bot behavior.
- New `/dashboard` live overview with mobile-friendly navigation and unified premium page styling. Existing Tasks, Connections, Studio and Assistant still use their existing server endpoints.
- Additional integrations and production actions (Discord server templates, YouTube OAuth uploads, GitHub coding agent, Pterodactyl redesign) are **future scoped, approved capabilities**, not implemented or linked automatically.
- See [Private Discord DMs and Dashboard](PRIVATE_DM_AND_DASHBOARD.md) for security boundaries and deployment tests.

## Step 55 — owner-only DM command fallback, capacity, and research

Global BOT_DM slash contexts and `!jarvis ...` owner-only DM text commands; read-only Pterodactyl node/server inventory, optional Brave Search API using encrypted vault, and admission-controlled 50 combined **pending/running** read-only task slots with memory-pressure backoff. Does not mean 50 active AI models, official Discord bot impersonation, remote cleanup, or Pterodactyl server mutation. See [Step 55](STEP55_DM_WORKERS_RESEARCH.md).

## Step 56: encrypted bot control, personal search API and local AI profiles

- Delivered protected `/bots` bot token identities, guild-only channel preview and individual owner-confirmed Discord messages; no self-bot or customer secret scraping.
- Delivered `/api/search` with owner session/CSRF or separate search-scoped API key, bounded backend results, rate limiting, and optional SearXNG loopback/Brave providers. Browser `/search` and existing owner DM commands use the same backend.
- Delivered optional local AI profiles (`efficient`, `adaptive`, `quality`) using only pre-installed Ollama models when cgroup RAM limits are verified. Defaults remain lightweight and no OpenAI API is configured.
- Not yet delivered: independent web index, automatic provisioning of remote nodes, automated customer data cleanup, unrestricted model-controlled account actions or general self-modifying production code.
- See [Step 56](STEP56_BOTS_SEARCH_LOCAL_AI.md).

## Step 57 — Root-only reversible Jarvis power toggle

- Added separate `esnjarvis status/off/on` Termius command with root-controlled state, original boot-enable preservation, safe startup/stop ordering and concurrency lock; no Wings, customer servers, Pterodactyl, Docker or Nginx changes.
- Ollama shutdown requires confirmed membership in the Jarvis resource slice; alternatively `off --keep-ollama` preserves shared model service.
- **OFF frees only RAM/CPU currently consumed**, not the full 8 GiB cgroup maximum and not installed disk files. A 5 GiB storage allocation is not a disk upgrade and is separate from this power switch.
- See [Step 57 deployment and rollback](STEP57_JARVIS_POWER.md). No VPS changes until the owner explicitly runs the opt-in installer/command.

## Step 58: verified customer-first Pterodactyl RAM scheduler policy

- Optional owner-enabled customer capacity mode checks local Wings UUID matching the exact Pterodactyl node and verifies memory/overallocation/physical host capacity before a bounded node.memory boost after Jarvis OFF.
- Restores the original scheduler cap BEFORE Jarvis ON; refuses restart when customers allocated the extra capacity, actual host RAM is insufficient, or the API cannot verify safe restoration. Does not alter individual servers or customer processes.
- If this VPS is not a Wings node, or the baseline already uses too much host RAM, the requested full 8192 MiB cannot be granted safely. No cross-node RAM transfer is possible.
- See [Step 58 reservation checks and activation](STEP58_CUSTOMER_CAPACITY.md).
