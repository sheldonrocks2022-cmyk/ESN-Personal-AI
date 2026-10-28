# Step 58 — Customer-first RAM allocation when Jarvis is OFF

## What this does and does not do

**Goal:** When ESN Jarvis is switched OFF on a VPS that ALSO hosts a Pterodactyl Wings node, make up to **8192 MiB of extra RAM scheduling capacity** available for customer servers on **that same VPS**, and preserve customer priority when turning Jarvis back ON.

This changes the Pterodactyl **node.memory** scheduling limit only; it does NOT preallocate 8 GiB of physical RAM, change an existing customer's server memory cap, create a new server, transfer RAM to a different physical node/VPS or add RAM to the machine. It cannot promise all 8 GiB extra will fit: host RAM and Pterodactyl's current base allocation must permit it with at least 2048 MiB left for Linux/system services.

The user's host has roughly 23 GiB RAM, of which ~19 GiB was available while idle. A Pterodactyl Wings node advertised at, for example, 16 GiB could **not** safely grow to 24 GiB on this host with 2 GiB reserved for the OS. The new preflight rejects that rather than overselling customers.

**Crucial:** This requires Wings installed on the **same VPS as Jarvis**. If no local \`/etc/pterodactyl/config.yml\` file or no exact match between its Wings UUID and the Application API node UUID, it refuses. This is intentional—Jarvis cannot transfer RAM to a different ESN VPS by turning off.

## Safe first step: read-only preflight

From root Termius, after updating the Git checkout:

\`\`\`sh
esnjarvis customers check
\`\`\`

This connects to the official ESN Pterodactyl Application API **read-only**; it validates the local Wings UUID, current node ID/memory, allocated customer RAM, memory overallocation, and physical host RAM. It uses \`PTERO_API_KEY\` and \`PTERO_BASE_URL\` from the existing protected \`/etc/esn-jarvis.env\` file; an Application API token with node-read and node-update permissions is required for final opt-in. Never paste that token into a chat, Discord message, screenshot or AI memory.

Possible fail-closed outcomes:
- \`No Wings UUID on this VPS\`: Jarvis's VPS is not a verified local customer node; dynamic Pterodactyl reservation here is impossible.
- \`PTERO_API_KEY ...\`: token is missing from the local service environment; configure it securely using your existing ESN admin workflow.
- \`Insufficient physical RAM\`: choose a smaller boost (256–8192 MiB) after verifying host/node budget, e.g. \`esnjarvis customers check --boost-mib 4096\`.
- \`overallocation\` or \`already overallocated\`: resolve existing node settings first; don't expand the allocation cap blindly.

No external changes are made by the check.

## Enable customer-first allocation mode (explicit owner opt-in)

Only if \`customers check\` passes, and only while Jarvis is currently ON:

\`\`\`sh
esnjarvis customers enable
\`\`\`

This saves a root-only (0600) configuration with local Wings UUID, numeric panel node ID, original Pterodactyl memory limit and exactly the verified extra MiB; it does **not** change the panel or stop Jarvis immediately. You can choose a smaller amount with \`esnjarvis customers enable --boost-mib 4096\` after checking.

**OFF:**
1. \`esnjarvis off\` checks physical host memory and exact node identity and confirms the panel's current allocation matches the original baseline.
2. Stops and disables ONLY Jarvis Discord, web/API and Jarvis-only Ollama. Saves its state atomically for recovery.
3. After all three are inactive, uses **PATCH /api/application/nodes/{id}** to change ONLY \`memory\` from the recorded baseline to baseline + verified boost, then reads back the node and verifies success.
4. Prints a warning that additional customer reservations can block Jarvis restarting. Customer servers are not changed or interrupted.

**ON (customer-first):**
1. \`esnjarvis on\` checks that panel customer allocations fit the original node baseline and that actual host available memory exceeds the planned Jarvis budget plus 2 GiB host reserve.
2. If those safety checks pass, it restores the original \`memory\` value via the official API and reads back to verify.
3. **Only then** does it restart Ollama, Jarvis web and Jarvis Discord, restoring their original systemd enablement.
4. If customers have allocated any RAM beyond the original node budget, or available RAM is insufficient, ON is **blocked** and Jarvis stays OFF. It never reduces current individual server allocations or kills a customer process.

**Status/disable:**
- \`esnjarvis status\` displays whether customer-first mode is enabled; no connection secrets are printed.
- \`esnjarvis customers check\` shows verified current panel allocation and customer usage.
- \`esnjarvis customers disable\` works only when Jarvis is ON and the panel is confirmed at the original baseline.
- \`esnjarvis off --dry-run\` prints service actions and the prospective node boost without changing anything.
- \`esnjarvis off --keep-ollama\` is deliberately incompatible with customer-first mode because an active shared Ollama could still consume the extra RAM.

## Security boundaries

- Token is read only from the root-owned 0600 \`/etc/esn-jarvis.env\` and never returned in errors, logs or model prompts.
- Target endpoint is fixed HTTPS \`https://panel.esnoffical.com\` with redirects disabled, not an arbitrary URL.
- The script validates local \`/etc/pterodactyl/config.yml\` Wings UUID against the precise panel node, refuses third-party or cross-VPS node changes.
- API writes change **only** the node's advertised RAM capacity field; no other panel node settings, user servers, backups, allocations, eggs, ports, disk quotas or server restarts are modified.
- It refuses any nonzero RAM overallocation or existing allocations exceeding baseline.
- It checks host RAM physical size and a 2 GiB OS reserve before increasing Pterodactyl's scheduler capacity.
- Disables/ON changes run under the same root-only file lock as the existing power controller and preserve original per-unit enable state.
- Stop/start operations never touch Wings, Docker, Nginx, Pterodactyl services or unrelated VPS nodes.
- Preflight is optional: when customer-first mode has not been enabled, \`esnjarvis off/on\` continues its earlier normal behavior with NO Pterodactyl API writes.

## Important limitations

- The Pterodactyl Application API is the scheduler limit; it cannot guarantee that Linux holds a 8 GiB idle pool physically reserved for customers. Linux RAM is shared dynamically; the customer-first interlock and total node scheduling budget enforce the intended policy without allocating dummy memory.
- If customer allocations expand during Jarvis OFF, the original node cap cannot be safely restored without reducing those allocations. The command deliberately leaves Jarvis OFF and asks the operator to move/reduce affected workloads or continue hosting with Jarvis OFF.
- If API credentials expire or the panel is temporarily unavailable, Jarvis may remain OFF until an administrator restores connectivity; that is safer than starting its 8 GiB AI budget atop potentially overallocated customers.
- "Reserved for customers" applies ONLY to a Wings node on this exact same VPS. Other ESN VPS nodes do not share physical RAM, and cannot benefit unless workloads are migrated.
- The current user's screenshot shows Jarvis ON and health passing. It does not establish that this VPS also hosts Wings; \`customers check\` must verify that before any commitment to a Pterodactyl allocation change.

## Verification and recovery

\`\`\`sh
esnjarvis customers check
esnjarvis off --dry-run
esnjarvis off
esnjarvis customers check
esnjarvis on
\`\`\`

Only test actual OFF/ON after confirming local Wings identity, node allocations, and no active customer reservations would exceed the restored baseline. If ON is blocked, keep customer servers running and inspect \`esnjarvis customers check\` and \`esnjarvis status\`, without editing the saved recovery file or forcing \`systemctl start ollama\`.

No user tokens, DNS settings, payment links, customer files or current ESN panel theme are modified by this feature.
