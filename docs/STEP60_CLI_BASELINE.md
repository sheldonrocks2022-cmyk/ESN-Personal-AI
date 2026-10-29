# Step 60 — Correct the oversized Node 1 limit from Termius (no panel clicking)

## What the user reported

- Local Wings UUID matches ESN Pterodactyl node ID **1**.
- Physical RAM: **24,032 MiB**.
- Panel Node 1 memory allowance: **4,294,967,295 MiB** (~4 PiB, unrealistic).
- Customer RAM already allocated: **9,216 MiB**.
- Jarvis systemd slice remains capped at **8 GiB** RAM (maximum, not a permanent reservation).
- `customers plan` proposes **11,264 MiB** customer allowance with Jarvis ON and **19,456 MiB** with Jarvis OFF.

The user prefers Termius/API commands and does **not** want to manually edit Pterodactyl Panel settings.

## New CLI workflow

```sh
# 1. Read-only preview: NO API PATCH.
esnjarvis customers baseline --node-id 1

# 2. ONLY IF preview is verified and change is approved:
esnjarvis customers baseline --node-id 1 --apply

# 3. Confirm new finite limit; read-only:
esnjarvis customers check

# 4. Optional separate step when the baseline is correct:
esnjarvis customers enable
```

The **default** `baseline` invocation is a preview. `--apply` must be explicitly specified for the administrative panel node-memory update. To avoid targeting the wrong node, `--node-id` is mandatory; the command also matches the local VPS Wings UUID against the official ESN Panel node before any change.

### Guardrails on `--apply`

- Must run from root and hold the same systemd power-controller lock.
- Jarvis web, Jarvis Discord and Ollama must be **ON/active**. The command refuses if the power-off state file exists.
- Cannot run if customer-first mode is already enabled.
- Must find a **uniquely matching local Wings node**; refuses cross-VPS and mismatched node IDs.
- The current node limit must be **obviously impossible**, larger than physical host RAM. Will not overwrite an already finite/legitimate customer node budget.
- Refuses if current customer allocations exceed the proposed ON limit.
- Refuses RAM overallocation or host/RAM changes after verification.
- Re-reads actual node state before applying, then applies only the `memory` scheduler limit using Pterodactyl's Application API, preserving all verified required node settings. It never changes an individual server's memory, disk, startup config or allocation.
- Reads back the node memory limit and reports success only if the new baseline is confirmed.
- **No customer server shutdown, Wings restart, Docker restart, AI restart, user credentials printed, extra RAM purchase, or node relocation.**

## Important nuance

Reducing an absurd node scheduling ceiling is a **real Pterodactyl panel configuration change performed remotely through its authorized API**, even though the user does not need to visit the UI. It reduces future allocation availability reported by the panel but does not reduce existing individual server resource limits. Users/admins who bypass placement rules may still overcommit the VPS; this is a safety policy rather than a physical reservation.

After applying, `esnjarvis customers enable` records the finite 11 GiB ON and 19 GiB OFF limits for the existing power switch. It still requires an explicit user choice and can block Jarvis restart when customer allocations exceed the ON budget.

For the root user on the VPS, existing `/usr/local/sbin/esnjarvis` points to the current Git checkout, so no new manual installer is required. First update the Git checkout via Termius after CI has passed.

Official Pterodactyl Application API: https://docs.pterodactyl.io/v2/api/application-api/applicationUpdateNode
