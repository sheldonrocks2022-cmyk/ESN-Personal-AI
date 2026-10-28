# ESN Jarvis v0.5: safe chat-to-tools bridge

## What works

With an owner-provided model API key configured **on the isolated Jarvis server**, the assistant UI at `/assistant` can interpret messages such as:

- "Check all ESN hosting nodes"
- "Check whether the panel is reachable"
- "Scan the ESN website's public page"
- "Check the public Jarvis GitHub repository"

The assistant uses model **function calling** to request a real job. The server—not the language model—validates the requested job against `operations.TASK_KINDS` and a fixed target allowlist before writing it to SQLite. Chat returns the **real queued job ID** and directs you to `/tasks` for the verified result. It never says the check completed just because the model requested it.

## Security controls

- Owner-token **and PIN** session required to unlock Connections; `/assistant` and `/api/assistant/chat` reject unauthenticated visitors.
- Browser session writes require the configured trusted origin and CSRF header; an independent bearer token can be used for trusted API clients.
- The model cannot directly run shell commands, execute arbitrary browser actions, charge a payment, modify DNS, restart or delete customer servers, issue Discord moderation commands, or access the vault.
- The exposed tool schema has exactly one tool, `queue_esn_check`, and the server validates inputs *again*. At most 3 tool calls per response.
- Recognizable access tokens are rejected before submission to the external model. **Do not type any secrets** in the assistant message box.
- Saved chat messages currently live in local SQLite; protect the disk, backups and owner service environment. Model conversations leave the private host when an external LLM provider is used.

## Activate

1. Follow [isolated deployment](DEPLOY_V04.md). The configured A record alone does not start Jarvis.
2. Add `OPENAI_API_KEY` to the protected, root-owned service environment. Configure `OPENAI_MODEL` for a tool-capable provider model.
3. Restart the service, sign in at `https://jarvis.esnoffical.com/connections` with your **new** PIN and independent owner token, then open `/assistant`.
4. Request a read-only check and use `/tasks` to verify the real job ID, status, and results.
5. Test wrong-PIN denial, direct unauthenticated /assistant requests, CSRF rejection, and secret filtering.

## Limits

This is an **early agent bridge**, not general unrestricted computer use or a fully autonomous agent. Live API calls, DNS resolution and production deployment have not yet been verified. The next implementation milestones are explicit owner approval gates and separate, reviewed connectors (GitHub branch/PR writes, creative-app automation, Discord, Stripe, Pterodactyl). No CAPTCHA bypass or unsupported identity-verification automation.
