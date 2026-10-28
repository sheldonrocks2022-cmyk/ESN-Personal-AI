# Step 55 — Owner DM commands, search, panel inventory and 50-slot queue

## Completed capabilities

**Discord bot DMs** now explicitly register globally for both server and bot-DM slash-command contexts, while prohibiting group-DM contexts. The bot remains guild-installed; it does not request permission to operate as your personal Discord user account. If the Discord mobile app still hides slash commands, the owner can type `!jarvis help` directly in the ESN Jarvis bot DM to access owner-only text equivalents for the current Jarvis commands.

The configured `DISCORD_OWNER_USER_ID` is checked *before* the DM fallback is invoked. Guests continue to receive `This bot is private` unless temporarily granted general chat access. The guest AI never receives owner commands, node tools, vault credentials or owner memories.

Text DM command examples:

- `!jarvis help`
- `!jarvis status`, `!jarvis disk`, `!jarvis capacity`
- `!jarvis panel nodes` and `!jarvis panel servers` — read-only Application API inventory, requires `PTERO_API_KEY`
- `!jarvis check panel_health`, `!jarvis tasks`, `!jarvis schedules`
- `!jarvis remember key | detail`, `!jarvis memories`, `!jarvis forget key`
- `!jarvis auto Audit ESN panel and website`; then `!jarvis approve UUID`, `!jarvis plan UUID`, `!jarvis cancel UUID`
- `!jarvis grant 123456789012345678 30 12`, `!jarvis guests`, `!jarvis revoke 123456789012345678`
- `!jarvis search latest Pterodactyl setup guide`

The corresponding new owner-only slash commands are `/jarvis_capacity`, `/jarvis_search`, `/jarvis_panel_nodes`, and `/jarvis_panel_servers`.

## Resource-budget reality

There are now **50 logical queued/running work slots** combined across the regular operations queue and autonomous plan steps. This does **not** create 50 OS worker threads or 50 simultaneous Qwen models. Existing single-threaded read-only operations and autonomous worker loops each process one check at a time, at most two independent checks. When the local verified 8 GiB memory slice approaches its 7 GiB throttle target, no *new* checks begin until enough RAM is available. The existing cgroup MemoryMax still enforces the hard 8 GiB limit. Heavy AI inference remains serialized by Ollama's existing limits.

The authenticated new `/api/operations/capacity` endpoint and the `/dashboard` capacity card display the real queued count and memory-guard state. A filled queue rejects extra jobs, rather than spawning more tasks. Pending schedules can be skipped at capacity.

This is a **capacity budget**, not proof of 50 parallel workers. Do not misrepresent it as 50 simultaneous browser or AI sessions.

## Web research: optional Brave Search

Jarvis can search web result titles/snippets through the official Brave Search API on an explicit owner request, without arbitrary web browsing, javascript execution, or clicking results.

Configure either:

1. Set `BRAVE_SEARCH_API_KEY` securely in the private Jarvis service's root-owned environment file; or
2. Save a `kind=other` connection named `Brave Search` with its subscription API key through the existing encrypted Connections vault, and set **only** `BRAVE_SEARCH_CONNECTION_ID=<vault ID>` in the root-owned service env.

The existing `esn-jarvis-discord` service must inherit the config; never paste the secret into Discord or chat. In the absence of configuration, `!jarvis search` and `/jarvis_search` report that the feature is unavailable. Queries and result summaries are shared with the search provider; exclude private customer data, passwords, personal DMs and server secrets.

This first version does not autonomously follow web links or grant its model external browser access. Search results are labelled unverified.

## Panel management and Discord bots: boundaries

Existing `PTERO_API_KEY` allows Jarvis to read nodes and servers through the **Application API**. It does not inherently authorize writes or authenticate other Discord bot identities. A Pterodactyl environment variable can contain a hosted application's Discord token, but Jarvis must **not** scrape that token or attempt to log in as arbitrary bots. To manage a hosted bot's process and files, use specific authorized Pterodactyl Client API scopes or an approved deployment workflow, with confirmed ownership and rollback. To act as another Discord bot, that bot's owner must separately authorize its application credentials through the encrypted vault.

Future owner-approved management stage: discover templates/eggs, allocations and quotas, draft server provisioning plans, validate no customer allocations are displaced, get per-plan explicit owner approval, create only the requested new servers through official API endpoints, audit results and enable rollback. Deleting, suspending, refunding or mass provisioning will not run without a separate reviewed workflow.

## Deployment and troubleshooting

Before pulling updates, confirm why the last `curl http://127.0.0.1:8765/health` reported connection refused after both units were briefly active. An immediate `systemctl is-active` does not confirm the web service has finished starting. Obtain `systemctl status esn-jarvis`, `journalctl -u esn-jarvis -n 40 --no-pager`, and a later local curl check. Do not change Nginx, Wings, Docker or customer services to resolve a slow web startup.

After CI succeeds and the PR is merged, pull as `esnjarvis`, run unit tests, restart **only** `esn-jarvis` and `esn-jarvis-discord`, and verify both live plus the authenticated dashboard. Do not save bot tokens to screenshots, logs or model memory.

## Next phase, not yet implemented

Approved Pterodactyl write workflows with rollback, protected multi-node cleanup agents, Discord guild setup templates, separate authorized bot deployment workflows, and self-editing GitHub coding agents. None can be safely inferred from mere panel visibility, and no remote-node cleanup was executed by the storage audit feature.
