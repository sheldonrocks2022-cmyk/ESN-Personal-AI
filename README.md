# ESN Jarvis / Personal AI

This is the recovered ESN Tab.bot-style AI project. Development resumes here; nothing from the earlier ESN hosting infrastructure has been replaced.

**This is a public GitHub repository. NEVER upload tokens, production secrets, customer records or backups.**

## Implemented v0.1
- Owner-token authenticated local HTTP API (loopback-only by default)
- Optional AI chat via an owner-provided OpenAI API key; conversation history stored in local SQLite
- Background jobs with real UUIDs and SQLite status records
- Read-only Pterodactyl panel health, nodes and servers
- Whitelisted jobs; no production mutations
- Automated unit tests via GitHub Actions (Python 3.13)

**Not built yet:** WhatsApp, Discord chat, autonomous browser, multi-agent worker system, GitHub editing agents, Stripe billing automations, customer server provisioning, ESN Guardian/Minecraft operations, media rendering and automatic Pterodactyl panel redesign. See [master roadmap](docs/ROADMAP.md).

## Setup: isolated environment only

Requirements: Python 3.11 or newer; no third-party packages. Use the approved isolated node, **never as root on a customer node**.

1. Get this repo onto the isolated host (via Git/SSH).
2. Configure environment variables from [the template](.env.example). Make `ESN_OWNER_TOKEN` a random 32+ character secret and do not send it in chat.
3. For monitoring, configure a **read-only** Pterodactyl Application API key from [panel.esnoffical.com/admin/api](https://panel.esnoffical.com/admin/api).
4. Run `python3 -m unittest discover -s tests -v`, then `python3 jarvis.py`.
5. Keep `ESN_BIND=127.0.0.1`. Use Termius SSH port forwarding or a properly secured HTTPS reverse proxy; never expose plain HTTP directly to the internet.

### API examples (from the isolated host)

```bash
curl -H "Authorization: Bearer $ESN_OWNER_TOKEN" http://127.0.0.1:8765/api/status
curl -H "Authorization: Bearer $ESN_OWNER_TOKEN" -H 'Content-Type: application/json' -d '{"type":"nodes_snapshot"}' http://127.0.0.1:8765/api/jobs
curl -H "Authorization: Bearer $ESN_OWNER_TOKEN" http://127.0.0.1:8765/api/jobs
```

Chat: with `OPENAI_API_KEY` configured, POST `{"message":"Hello Jarvis"}` to `/api/chat`. Recent conversation text goes to the configured AI provider. Do not send customer details or credentials.

## Security and maturity

This is an owner-only **prototype**, not a production hardened service. It has no customer-server write permissions. The database is stored in plaintext; use volume encryption and filesystem permissions. Future stages need TLS, rate limiting, safe backups and a stronger worker queue.

## Panel redesign

A [preliminary audit](docs/PANEL_AUDIT.md) documents your existing theme scripts in `Esn-2`. The public live panel could not be fully inspected, so no design changes were deployed. Staging, screenshots, visual testing and owner approval come before touching production.
