# Step 61: Remove Jarvis from this VPS (owner-requested)

This is a **permanent** deletion of the Jarvis **local installation**. It destroys Jarvis's local application, venv, data, local encrypted connection vault, owner token, saved API keys, task records and bot services. **This cannot be undone without reinstalling and restoring backups.**

## One Termius command

Run from the root Termius shell on the known Jarvis VPS:

```sh
runuser -u esnjarvis -- git -C /opt/esn-jarvis/app pull --ff-only origin main && python3 /opt/esn-jarvis/app/scripts/uninstall_jarvis.py --apply
```

The script checks for known Jarvis ownership of exactly named local systemd/Nginx paths, guards against symlinks and nested mounts, stops and disables the **two dedicated** Jarvis services, removes their service units and dedicated systemd budget drop-ins, removes Jarvis's Nginx vhost with test/reload rollback, deletes the exact app directory, power control wrapper, Jarvis-only environment, power state and ACME challenge directory.

Never runs `rm -rf` on untrusted paths. Never calls Pterodactyl to change server memory limits. Never stops Wings, Docker, the panel, Nginx, customer services, or other ESN nodes.

If `/etc/esn-jarvis-customer-capacity.json` exists or a saved OFF state contains a customer RAM policy, **the deletion refuses to run** rather than orphaning the node allocation switch. Disable customer-first mode safely while Jarvis is ON and node allocation has returned to its configured baseline, then retry.

## What remains (intentionally)

- **Pterodactyl Node 1** and all existing customer servers/configuration. Its advertised RAM limit stays unchanged (last known **11264 MiB**, 11 GiB), even though Jarvis is removed. Raising it safely is a separate owner-approved panel API action; it is not a physical reservation.
- **System Ollama** binary, shared service, model blobs, and any its ESN-specific systemd quota references. These may be consumed by other apps; don't uninstall them without checking. They might still consume RAM after Jarvis is gone.
- **Certbot** certificate and any renewal files for `jarvis.esnoffical.com`, and **Spaceship DNS** records. Separate revocation/removal requires checking those aren't shared.
- **GitHub repository** `sheldonrocks2022-cmyk/ESN-Personal-AI` and any GitHub Actions/remote backups; deleting the local checkout does not delete the remote repo.
- Existing **Discord application/bot registration**; revoke its token or delete the app separately in Discord's Developer Portal if wanted.
- Active **Pterodactyl API keys**: deleting the local file does not revoke them. Revoke the Jarvis-specific key in the Admin API panel when no longer needed.
- Any external databases or media storage not located under `/opt/esn-jarvis`. The script deliberately does not infer or delete arbitrary external paths from environment variables.

## Optional preview

```sh
python3 /opt/esn-jarvis/app/scripts/uninstall_jarvis.py
```

Preview performs no deletions. The `--apply` command immediately executes, with no further prompts, because the owner explicitly requested a one-command uninstall.

If it aborts, inspect its error and do NOT manually delete root folders or customer files. That guard is intended to prevent accidental deletion of unrelated hosting resources.
