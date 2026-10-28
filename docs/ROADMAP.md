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
