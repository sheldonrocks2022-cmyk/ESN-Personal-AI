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
