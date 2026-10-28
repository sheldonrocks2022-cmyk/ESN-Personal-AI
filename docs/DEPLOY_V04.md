# ESN Jarvis v0.4 — isolated deployment and test checklist

**Status:** Code and tests only. DNS records alone do not deploy software. Do not run this app as root or on customer Pterodactyl/Wings nodes. Do not overwrite the existing `panel.esnoffical.com` Nginx configuration.

## Before you start

- Deploy to a **dedicated, isolated VPS** with a stable public IP. Keep port 8765 bound to 127.0.0.1.
- In Spaceship Advanced DNS, ensure `jarvis.esnoffical.com` has an A record to that **isolated VPS IPv4**. The user reports DNS is configured, but we cannot independently confirm resolution in this development environment.
- Require HTTPS with a trusted certificate and use a VPN or additional identity gateway for vault use.
- Have Python 3.11+ (3.13 tested), Git, FFmpeg/FFprobe (optional studio), Nginx and Certbot.
- Do not reuse the six-digit PIN previously posted in chat. Set your new PIN **on the VPS terminal** with no secret in the public GitHub repo.

## Create the service

```bash
sudo useradd --system --create-home --home-dir /opt/esn-jarvis --shell /usr/sbin/nologin jarvis
sudo git clone https://github.com/sheldonrocks2022-cmyk/ESN-Personal-AI /opt/esn-jarvis/app
# For v0.4 testing, check out the approved feature branch or merged commit explicitly.
sudo chown -R jarvis:jarvis /opt/esn-jarvis
sudo -u jarvis python3 -m venv /opt/esn-jarvis/venv
sudo -u jarvis /opt/esn-jarvis/venv/bin/python -m pip install -r /opt/esn-jarvis/app/requirements.txt
cd /opt/esn-jarvis/app
/opt/esn-jarvis/venv/bin/python -m unittest discover -s tests -v
```

Generate a fresh owner token privately (for example with `python3 -c 'import secrets;print(secrets.token_urlsafe(48))'`) and generate a vault key with `python3 -m connections generate-key`. Run `python3 -m connections hash-pin` to choose your new PIN interactively. Keep all three values outside GitHub and outside chat.

Create `/etc/esn-jarvis.env` with mode 0600, owned by root, containing:
```ini
ESN_OWNER_TOKEN=<unique random 32+ character secret>
ESN_VAULT_KEY=<Fernet key from CLI>
ESN_DASHBOARD_PIN_HASH=<PBKDF2 hash from CLI>
ESN_BIND=127.0.0.1
ESN_PORT=8765
ESN_DB_PATH=/opt/esn-jarvis/data/operations.sqlite3
ESN_PUBLIC_ORIGIN=https://jarvis.esnoffical.com
ESN_COOKIE_SECURE=1
ESN_CREATIVE_ENABLED=0
PTERO_BASE_URL=https://panel.esnoffical.com
PTERO_API_KEY=
```
Create `/opt/esn-jarvis/data` owned by jarvis. Only populate `PTERO_API_KEY` with a key restricted to **reading** the required nodes and servers. Leave it blank until ready.

### systemd example (isolated VPS only)

```ini
[Unit]
Description=ESN Jarvis private assistant
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=jarvis
Group=jarvis
WorkingDirectory=/opt/esn-jarvis/app
EnvironmentFile=/etc/esn-jarvis.env
ExecStart=/opt/esn-jarvis/venv/bin/python /opt/esn-jarvis/app/jarvis.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/opt/esn-jarvis/data
ProtectHome=true
UMask=0077

[Install]
WantedBy=multi-user.target
```

For creative workers, run a **separate isolated host/service** with `ESN_CREATIVE_ENABLED=1`, a dedicated writable `ESN_MEDIA_ROOT`, FFmpeg and configured `ReadWritePaths`. Do not run high-cost encoding on Pterodactyl customer nodes.

For private browser inspection, install optional Playwright on the isolated host:

```bash
/opt/esn-jarvis/venv/bin/python -m pip install playwright
/opt/esn-jarvis/venv/bin/python -m playwright install chromium
```

The browser inspector is **read-only and public-site-only**, targeting ESN Website and the public panel login page. It does not bypass CAPTCHA, conduct account sign-ins, or administer authenticated panel pages.

### HTTPS / Nginx

Use a **new** Nginx virtual host for `jarvis.esnoffical.com` proxying to `http://127.0.0.1:8765`, with `X-Forwarded-Proto https`, then obtain the TLS certificate via Certbot. Do not expose TCP 8765 publicly. A six-digit PIN **alone** is not suitable for an Internet-facing credential vault; the app also requires an independent owner token. Prefer a VPN/identity-aware gateway.

## Verify

1. `sudo systemctl status esn-jarvis`, then test local `GET /health`; do not infer the public URL is working from DNS alone.
2. Visit `https://jarvis.esnoffical.com/connections`. Verify correct owner token **and a new PIN**, failed login, expiration, logout and CSRF rejection.
3. Save a disposable test secret and confirm only encrypted ciphertext is stored in SQLite.
4. Visit `/tasks`. Run a panel health check, confirm a real job ID and verified result. If the remote panel cannot be reached, it should show failed rather than pretend success.
5. Create a recurring public website health check; restart Jarvis and verify the schedule persists.
6. Queue and cancel a test operation, check failures and bounded retries. Check that arbitrary endpoints and destructive commands are rejected.
7. With a dedicated media worker, run the Creative Studio logo and short MP4 tests and review actual output files.
8. Verify Discord connections using a disposable bot token before connecting ESN Guardian.
9. **Do not** enable customer-server writes, arbitrary shell tools, Stripe payments, or automatic production deployments without separate owner-approval workflows.

## Limits

This version adds durable read-only task automation and persistent creative job recovery. It does **not** implement unrestricted computer control, passkey enrollment, video-editor remote control, full multi-agent autonomy, customer provisioning, or arbitrary account actions. Those require distinct reviewed capabilities and secure integrations.
