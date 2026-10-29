# Step 59 — Oversized Node RAM Limit: READ-ONLY Corrective Plan

## Why your previous `customers check` refused the 8 GiB boost

The live Node 1 read-only output (user screenshot) states:

- Node ID: **1**
- Pterodactyl advertised memory: **4294967295 MiB** (approximately 4 PiB; impossible on this VPS)
- Allocated customer server RAM: **9216 MiB (9 GiB)**
- RAM overallocation setting: **0%**
- VPS physical RAM: **24032 MiB (about 23.47 GiB)**
- VPS current available RAM: **20056 MiB (about 19.6 GiB)**

Panel-advertised `memory` is an allocation scheduling limit, NOT host physical RAM. Official Pterodactyl documentation says to reserve space for the OS and other services, and clarifies that admins may bypass automatic placement limits. The existing Step 58 boost correctly refuses because an enormous panel limit cannot safely be increased again.

**We did not change any panel setting, restart Wings or change any customer server.**

## New read-only command

```sh
esnjarvis customers plan
```

This uses the existing protected panel key and local Wings UUID matching. It refuses nonzero overallocation and refuses any suggested ON limit smaller than current allocated customer RAM. It automatically rounds the OFF ceiling *down to a whole GiB*, keeps at least **4096 MiB for Linux and non-customer services**, then subtracts 8192 MiB for Jarvis ON. With the reported hardware, the proposed initial limits are:

| State | Customer node advertised RAM limit |
|---|---:|
| Jarvis ON | 11264 MiB = 11 GiB |
| Jarvis OFF | 19456 MiB = 19 GiB |
| Difference | 8192 MiB = 8 GiB |
| RAM outside customer limit in OFF mode | 4576 MiB = ~4.47 GiB |

The ON cap leaves 2048 MiB (2 GiB) unallocated above the already assigned 9216 MiB; this is a narrow margin and should be reviewed against actual workloads. The 8 GiB Jarvis limit is only a cap and not RAM preallocated. This plan is deliberately conservative but is not a guarantee against every burst, manual admin allocation, or unknown process consuming host RAM.

## Safety / approval boundary

The new command is **pure read-only**. It does not auto-correct `4294967295`, run `esnjarvis customers enable`, change panel RAM, edit allocations, move servers or restart services.

After reviewing `customers plan`, the owner may separately approve a finite baseline setting and deployment schedule. If the existing Node 1 limit is reset to a safe finite baseline by an authorized admin, the older Step 58 `esnjarvis customers check` and `enable` can then be used to configure ON/OFF changes. This is a **production panel configuration change**, so it must be staged when the operator has reviewed any affected provisioning automations, current/reserved resources, active customers and a rollback plan.

Do not set Node 1 to 19 GiB while Jarvis is still ON with an 8 GiB maximum; that oversubscribes available host RAM once Linux overhead is included. Do not reduce existing customer server RAM limits just to force the plan to pass. If advertised capacity was intentionally unlimited, explain why before changing it.

## Useful verification

1. Run `esnjarvis customers plan` and share **only the text output**.
2. Compare actual Pterodactyl reserved memory across all servers on Node 1; the Application API summary provides one allocation snapshot, not proof of all Docker/container usage.
3. Review whether Node 1 currently receives automatic provisioning from ESN business workflows; new limits will reduce the panel's reported placement headroom.
4. Once separately approved, test a customer-safe panel node-limit correction first, then test Jarvis's customer-first OFF/ON switch.

Official docs: https://docs.pterodactyl.io/v2/guides/configuration/add-node
