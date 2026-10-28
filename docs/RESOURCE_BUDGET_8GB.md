# ESN Jarvis: Shared 8 GiB RAM Budget

**Scope:** Ollama local model server, ESN Jarvis website/service, and the private ESN Jarvis Discord bot. These three services run on the same VPS as production Pterodactyl Wings. The resource budget **does not** include or modify Wings, Nginx, Docker, game servers, or the main ESN panel.

## Why a shared systemd slice?
Independent per-service limits do not impose a *combined* maximum, so this installs a parent `esn-jarvis.slice` with `MemoryMax=8G`, `MemoryHigh=7G`, `CPUQuota=200%`. Slice group membership comes from three narrowly scoped systemd service drop-ins. The existing individual limits (Ollama 4G, Jarvis 512M, Discord 384M) remain in place unless the operator later changes them deliberately.

MemoryHigh throttles under pressure. MemoryMax can cause an OOM termination *within Jarvis* instead of guaranteeing graceful operation. Idle memory is **not reserved**. Nothing in this feature upgrades AI quality, guarantees 8 GB availability at all times, or permits unrestricted actions. Model RAM/CPU depend on context, parallel requests and model choice.

## Production steps (Termius)

1. Update the repository with the tested merge, then preview as root:
   `python3 /opt/esn-jarvis/app/scripts/install_8gb_budget.py`
2. Inspect the exact list of four target paths. Apply **only if this is the intended shared Wings node** and no existing conflicting config:
   `python3 /opt/esn-jarvis/app/scripts/install_8gb_budget.py --apply`
3. The installer does not restart anything. During a safe maintenance window, run:
   `systemctl restart ollama esn-jarvis esn-jarvis-discord`
4. Verify actual slice membership:
   `systemctl show ollama esn-jarvis esn-jarvis-discord -p Id -p Slice -p ActiveState`
   Every service must report `Slice=esn-jarvis.slice`. If not, the cap does **not** apply to that service.
5. Inspect active cgroup budget:
   `systemctl show esn-jarvis.slice -p MemoryHigh -p MemoryMax -p ActiveState`
   `cat /sys/fs/cgroup/esn-jarvis.slice/memory.current`
6. Open `https://jarvis.esnoffical.com/tasks` and view the new **Jarvis RAM budget** display. A displayed 8 GB target is not proof that the cap is active; the dashboard verifies `memory.max`.

### Safety notes

- Keep Ollama bound to `127.0.0.1:11434`; do not expose the local model API to the public.
- Continue limiting Ollama parallel inference to 1 and loading only one model at once.
- High-resource video rendering, After Effects, CapCut or GPU work must run on an independent creative machine or external worker, not the customer Wings host.
- Before changing limits or increasing the model size, record peak memory, CPU latency and game-server performance.
- The installer uses exclusive file creation, refuses conflicting pre-existing configs, doesn't touch unrelated unit files, never restarts services automatically and never accesses secrets.
- The Task Center endpoint is owner authenticated and read-only.
- Rolling back: remove only the four `90-esn-budget.conf` and `esn-jarvis.slice` files created by this feature, run `systemctl daemon-reload`, and restart the three Jarvis services. Do not remove other drop-ins.

### Further capability milestones within the budget

1. Use small quantized local models and bounded context; add semantic memory with disk-backed retrieval.
2. Develop safe tool integrations (GitHub PRs, ESN read-only node monitoring, scheduling, Stripe reporting) with owner approvals for any writes.
3. Add browser/Desktop operator workers on isolated hosts, with owner handoff for verification challenges.
4. Send video rendering, compositing and more intensive design workloads to separate workers, keeping Jarvis's coordinator within 8 GB.
5. Measure actual performance and failures; upgrade quality via remote or specialized models when needed.
