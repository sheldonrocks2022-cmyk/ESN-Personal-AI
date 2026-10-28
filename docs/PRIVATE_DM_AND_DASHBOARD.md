# ESN Jarvis — Private Discord DMs and Command Center

## Delivered in this upgrade

Jarvis remains hosted on its existing node with the shared `esnjarvis.slice` 8 GiB RAM ceiling. The Discord bot and website remain separately restartable services.

### Owner DMs

- Directly DM the **ESN JARVIS bot** from the configured `DISCORD_OWNER_USER_ID`. Plain text goes to the same owner-only `jarvis.chat` method as `/jarvis_ask`, using the **existing** local Ollama provider configuration. This is NOT access to your private user-account inbox.
- Bot ignores ordinary messages in servers and group DMs, preventing unintended public chat replies.
- Slash commands are synced globally in addition to the configured guild so they can appear in DMs with the bot.
- Bot DM content is handled through Discord's official bot gateway exception; privileged guild-wide message content is **not** enabled.
- Your existing owner commands (memory, tasks, node snapshots, etc.) remain restricted to the configured owner ID.
- No owner token, PIN, API key, or credential is ever sent in a reply.

### Restricted guest DMs

- Unknown users receive exactly: `This bot is private` (limited to one automated refusal per 60 seconds per user to avoid floods).
- Only the owner may use `/jarvis_dm_grant user_id:<id> minutes:<5-1440> messages:<1-30>`.
- A grant is bound to a numeric Discord user ID, expires at an exact timestamp, has an atomic per-guest message budget and a six-second cooldown, and persists through restarts.
- `/jarvis_dm_revoke user_id:<id>` cancels access immediately. `/jarvis_dm_guests` shows active IDs, expiry and remaining allowance.
- Grants authorize **only general question answering**. They cannot access Jarvis tools, autonomous jobs, private owner history, owner memory, vault secrets, panel APIs, GitHub accounts, Stripe, Discord server management or any file.
- Guest requests go directly to local Qwen3 with an isolated system prompt and **no tools or saved chat history**. The database stores only permission metadata, not guest conversations.
- This does not initiate unsolicited DMs. An approved guest must DM the bot themselves.
- A question may already be in flight when a grant is revoked; any further questions are blocked. Replies are limited in length, with mention pinging disabled.
- The owner should not use this feature to impersonate another account or read messages not addressed to the bot.

### Jarvis Command Center V2

- An authenticated `/dashboard` overview displays actual local RAM usage, local disk capacity, recently completed tasks, and real autonomous-plan statuses from existing Jarvis APIs.
- Redesigned mobile-friendly top navigation, dark glass panels, improved typography and responsive spacing across `/connections`, `/assistant`, `/tasks` and `/studio`.
- Existing connections, login, tasks, video/logo jobs, API routes and Nginx configuration remain intact.
- The redesign is a first improved theme and shared shell, **not** a claim to exactly match `smp.esnoffical.com` without access to its visual design.

## Testing

The suite checks guest ID validation, time limits, message budgets, cooldown, regrant/revoke, max active guests, isolated model invocations, no tool calling, no persistent guest chat, authenticated dashboard access and page navigation.

Deployment after CI approval: Pull the merged `main`, run full tests/py_compile, restart only `esn-jarvis` and `esn-jarvis-discord`. After restarting, open `https://jarvis.esnoffical.com/dashboard` and then test a direct owner DM. If slash commands aren't visible immediately, verify the application was authorized with `applications.commands` and the bot has permission to send DMs to the relevant users.

If any unexpected issue occurs, roll back via Git and restart the two Jarvis services; do **not** change Pterodactyl, Wings or customer workloads.

## Requested future work — not implemented in this pull request

**Account integrations.** Connect services individually using official OAuth or access tokens with minimum scopes, owner approval and revocation. Do not automate normal Discord user logins or collect user tokens. Discord prohibits self-bots: a bot can read its own DMs and authorized guild messages, but can't read your personal DM inbox. A voluntary share/forward workflow can provide messages you want Jarvis to summarize.

**Discord server and bot construction.** Add templates that can create channels, roles, categories and permissions inside guilds where Jarvis is an explicitly authorized bot with the necessary Discord permissions. Building new bot applications requires supported developer workflows and separate application credentials; no unrestricted mass guild creation, spam or rate-limit evasion.

**YouTube publishing.** Official YouTube Data API upload integration with Google OAuth `youtube.upload` scope, encrypted refresh token, channel verification, metadata preview, owner confirmation on every publish, rate limits and upload-status tracking. The current creative studio only produces files; it does not post to your account yet.

**Panel/site redesign.** Obtain screenshots/assets of `smp.esnoffical.com`, identify the exact visual language, and redesign additional Jarvis pages in an isolated preview environment. For Pterodactyl, use version-specific staging before any production changes.

**Self-programming.** Authorized repo-specific GitHub scopes, branch-based code edits, automated tests/security scanning, resource benchmarks, PR review, explicit production deployment approvals and rollback. Do not permit an agent to rewrite its own running code or download untrusted scripts straight into the customer node.

**Resource budget.** Keep shared 8 GiB RAM and CPU limits; offload heavy coding builds, video renders, browser sessions and AI work to isolated workers.
