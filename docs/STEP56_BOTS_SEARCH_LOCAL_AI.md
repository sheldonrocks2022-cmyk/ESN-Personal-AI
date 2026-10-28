# Step 56 — ESN Jarvis Multi-Bot Access, Private Research API, Local AI Profiles

This step adds **real, owner-authorized capabilities** without expanding the running VPS past the existing shared 8 GiB systemd ceiling. Jarvis still runs local Qwen3 by default. No OpenAI integration, no automatic model downloads, no multi-process LLM swarm, no customer modifications.

## 1. Connect YOUR Discord bot tokens

1. Sign in to [Jarvis Connections](https://jarvis.esnoffical.com/connections) with your owner token and PIN.
2. Select `Discord bot token`, enter a label (for example `ESN Guardian`), and paste **that bot's** token into the secure password field. Never put tokens in Discord DMs, chat, AI memory, screenshots, GitHub or logs.
3. Open [Managed Bots](https://jarvis.esnoffical.com/bots). Choose the saved connection and click **Verify bot identity**. Jarvis uses Discord's official `GET /api/v10/users/@me` with `Authorization: Bot <token>`.
4. Enter a guild text/announcement channel ID and click **Verify channel**. Jarvis checks the channel using the same bot's authorization and rejects DM/group DM/voice destinations.
5. Enter the exact message you want and click **Review & send one message**, then explicitly confirm. Jarvis submits one `POST /channels/{id}/messages` with mention pings disabled. There is a 30-second per-bot cooldown and a 10-per-bot/30-global attempt cap in each 24-hour window. Only send into servers where you have permission.

The existing `vault_connections` table encrypts tokens using `ESN_VAULT_KEY`. No new credential store, root access or bot-token scan is installed. Each bot is separately selected and revocable by deleting its connection. A token only authorizes that bot identity. It cannot access your personal Discord account, normal personal DMs or other bots. There is no automatic login to arbitrary apps. Nothing reads bot tokens out of Pterodactyl containers.

New owner-only Discord commands:
- `/jarvis_bots`, `/jarvis_bot_check`, `/jarvis_bot_send` (explicit `confirm=true`).
- Text DM fallback: `!jarvis bots`, `!jarvis bot CONNECTION_ID`, or `!jarvis bot-send CONNECTION_ID CHANNEL_ID | message`.

Existing `/jarvis_ask`, `/jarvis_remember`, `/jarvis_auto`, `/jarvis_dm_grant`, `/jarvis_dm_revoke` and the `!jarvis` owner text commands remain intact. Guests remain chat-only and cannot call these bot actions.

## 2. Jarvis's OWN search API

Your Jarvis server serves:

- `GET https://jarvis.esnoffical.com/api/search/status` — backend configuration and capabilities.
- `POST https://jarvis.esnoffical.com/api/search` — JSON body `{"query": "Pterodactyl official docs"}`, returning `provider`, `query`, a bounded list of title/link/snippet records and a warning that results are unverified.
- Owner website [Research](https://jarvis.esnoffical.com/search) — query form and results.
- `/jarvis_search`, `!jarvis search ...`, and the literal owner request `Search the web for ...` use the same backend.

**Access control:**
- A Jarvis owner dashboard cookie with Origin and CSRF headers, OR
- An independent, random, at-least-32-character `ESN_SEARCH_API_TOKEN` set only in `/etc/esn-jarvis.env`. Then other trusted apps can send `Authorization: Bearer <ESN_SEARCH_API_TOKEN>`. A search-only key does **not** work on your bot, vault, node or AI endpoints.
- API rate limit: 20 requests per minute per credential/session. No cross-origin web access is enabled.
- Never send secrets, private DM contents or customer data as search queries.

**Backends:**
1. Default `JARVIS_SEARCH_BACKEND=brave`: Save an encrypted connection of type **Brave Search API key** in Connections. Jarvis auto-selects the latest stored search token, or uses an explicitly configured `BRAVE_SEARCH_CONNECTION_ID` or `BRAVE_SEARCH_API_KEY`. The key stays on the host; normal provider API usage rules apply.
2. Optional self-hosted SearXNG: Set `JARVIS_SEARCH_BACKEND=searxng` **only after** installing a protected SearXNG instance on loopback `127.0.0.1:8888` with JSON format enabled. Jarvis makes bounded GET requests to that exact address only. SearXNG is a metasearch service that forwards queries to external engines—not an independent internet index. **No SearXNG service is installed by this GitHub update**, and its extra memory cost must be measured separately.

Search results are untrusted third-party text. Jarvis never executes commands from search results, follows returned links automatically, bypasses CAPTCHA, or opens arbitrary URLs in an owner session. Model-generated searches are disabled unless the owner supplies the explicit query.

## 3. Highest useful AI capability under the 8 GiB budget

This update keeps `OLLAMA_MODEL=qwen3:1.7b` and `ESN_AI_PROFILE=efficient` as default. There is no forced downgrade/upgrade, model download or additional worker process.

Optional settings in the host's protected environment:

- `ESN_AI_PROFILE=efficient` — always use the fast configured local model.
- `ESN_AI_PROFILE=adaptive` — use the optional quality model only for clearly complex owner requests (coding, debugging, design, reasoning) when **explicitly installed** and the verified Jarvis cgroup has enough free RAM. Ordinary questions and guests stay on the fast model.
- `ESN_AI_PROFILE=quality` — prefer the optional quality model for owner requests when it is installed and the memory budget allows.
- `OLLAMA_MODEL_QUALITY=qwen3:4b` — an *example*, not automatically installed. Choose any locally supported quantized quality model that fits available RAM. Benchmark performance first. Model validation permits only safe model names, and all Ollama traffic stays at `127.0.0.1:11434`.

Existing `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_KEEP_ALIVE=0` and the systemd `esnjarvis.slice` 8 GiB limit remain unchanged. CPU-only 2-core inference will be slow for larger models; this step does not magically make a small model equal to frontier cloud AI. Tool design, scoped integrations, tests and retrieval improvements are what will make Jarvis more useful.

## 4. Deployment — DO NOT mix with a broken startup

Your last screenshot showed both units briefly `active` while the immediate `curl 127.0.0.1:8765/health` failed. Before updating, verify with:

```sh
systemctl is-active esn-jarvis esn-jarvis-discord
sleep 4
curl -fsS --max-time 10 http://127.0.0.1:8765/health || journalctl -u esn-jarvis -n 40 --no-pager
```

This release only changes Jarvis's app code and web pages, not systemd, Nginx, Wings, customer servers, node allocations or Ollama configuration.

After the web service is confirmed healthy, pull the merged `main` as `esnjarvis`, compile/execute the full tests, and restart only `esn-jarvis` and `esn-jarvis-discord`. Check health again once systemd has finished binding port 8765.

## 5. Future separate integrations

- Permissioned Pterodactyl provisioning, allocation checks, server lifecycle commands and reversal workflows.
- Remote node storage agents, dry-run cleanup and specific owner-approved reversible changes.
- GitHub coding-agent worktrees/branches, tests, PR approvals and versioned deployments.
- YouTube OAuth uploading/previewing and permissioned Discord server templates.
- Provider-specific apps via OAuth/API keys and owner approval, never blanket account password harvesting or unbounded self-modification.

All such actions require additional verified tools and user authorization; connecting a credential does not automatically grant unrelated permissions.
