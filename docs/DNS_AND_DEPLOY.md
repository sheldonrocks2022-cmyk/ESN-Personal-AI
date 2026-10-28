# ESN Jarvis private Connections dashboard — DNS & deployment guide

These are **planned configuration steps**. No DNS records or deployment have been made from this repository. The Jarvis dashboard is separate from `panel.esnoffical.com` and must not overwrite existing panel DNS, Nginx, Pterodactyl or Wings settings.

## Spaceship DNS

In Spaceship → Domain List → `esnoffical.com` → DNS / Advanced DNS, add:

| Record | Host | Value | TTL |
| --- | --- | --- | --- |
| **A** | `jarvis` | **public IPv4 of the isolated Jarvis host** | Auto or 300 seconds |
| AAAA (optional) | `jarvis` | IPv6 of that host, only if IPv6 is configured and routable | Auto |

The resulting destination will be `jarvis.esnoffical.com`. **Do not use an existing Pterodactyl node's IP unless you intentionally host the dashboard there and have isolated it appropriately.** A separate host is preferred. Do not delete or edit `panel`, node or existing root DNS records. If you have only a hostname provided by your hosting company instead of a stable IP, use a `CNAME` for `jarvis` pointing at that hostname *instead* of the A/AAAA records. No registrar nameserver changes are needed if Spaceship already hosts your DNS.

## Minimal isolated server configuration

1. On a dedicated isolated Linux server, install Python 3.11+, Git, Nginx and Certbot. Keep `jarvis.py` running under a restricted non-root system service, using a root-readable environment file that is not in the public web root or Git repository.
2. Use `python3 -m pip install -r requirements.txt`; run `python3 -m connections generate-key` to create a vault key and `python3 -m connections hash-pin` to enter your PIN privately. Store these in the private service environment. Create an independent **32+ character random** `ESN_OWNER_TOKEN`. Set `ESN_BIND=127.0.0.1`, `ESN_PORT=8765`, `ESN_PUBLIC_ORIGIN=https://jarvis.esnoffical.com`, `ESN_COOKIE_SECURE=1`.
3. Keep TCP 8765 closed to the public. Configure Nginx to reverse-proxy `jarvis.esnoffical.com` to `http://127.0.0.1:8765` with the `Host` header passed through. Restrict access to the dashboard further using VPN or an identity-aware access proxy if possible.
4. Issue and automatically renew a valid HTTPS certificate for `jarvis.esnoffical.com` with Certbot (e.g., `sudo certbot --nginx -d jarvis.esnoffical.com` after the host and DNS are ready). Redirect HTTP to HTTPS. Never enter owner credentials on plain HTTP.
5. Run the automated tests and verify HTTPS, PIN+owner-token login, wrong-PIN rejection, CSRF rejection, encrypted vault save/list/remove, Discord bot validation, and owner-only slash commands **before** treating this as production-ready.

Example Nginx vhost body **before Certbot** (this is a template; do not replace existing panel vhosts):

```nginx
server {
    listen 80;
    server_name jarvis.esnoffical.com;
    client_max_body_size 32k;
    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 30s;
    }
}
```

## Security notes

- A six-digit PIN is not sufficient authentication for an internet-accessible credential vault. This implementation requires the PIN **and** the independent owner token; it also rate-limits login attempts. Add a trusted identity provider or hardware security key before broad public exposure.
- The PIN supplied in chat should be treated as exposed; change it privately when configuring the server. Never commit the PIN itself or its hash to the public repository.
- Do not store passwords in ESN Jarvis's AI chat history. Use the Connections page, where values are encrypted at rest and never displayed again.
- Back up the encryption key separately and securely; losing it makes credential recovery impossible. Maintain encrypted, permission-restricted database backups.
- Any Pterodactyl/Stripe/GitHub integration should use the lowest privileges required and remain read-only until the user approves particular write operations.
