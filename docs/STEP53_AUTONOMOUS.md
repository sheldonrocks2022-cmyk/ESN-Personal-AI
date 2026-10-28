# Step 53 — ESN Jarvis autonomous task engine (safe foundation)

This introduces a **real, restart-durable, owner-approved multi-step audit engine**. Jarvis can break an approved ESN health-check request into a bounded plan, execute read-only checks sequentially, and show actual results. It is not a general-purpose unattended computer controller or a code-writing agent yet.

## Where to use it

- Discord: \`/jarvis_auto\` with goal \`Audit ESN panel, website and GitHub\`.
- Jarvis displays the planned steps and a unique UUID. Nothing runs until you choose \`/jarvis_auto_approve\` with that ID.
- \`/jarvis_auto_status\` shows step progress. \`/jarvis_auto_cancel\` cancels remaining queued work.
- The owner-authenticated Task Center at \`https://jarvis.esnoffical.com/tasks\` now has **Autonomous plans** with the same create, review, approve, cancel and inspect functions.

## What it can execute now

- \`panel_health\` — checks the public Pterodactyl login endpoint.
- \`esn_website_health\` — checks the public ESN website.
- \`github_repo_health\` — queries the public ESN-Personal-AI GitHub repository.
- \`nodes_snapshot\` and \`servers_snapshot\` — permitted **read-only** metadata via the existing Pterodactyl Application API. These require an already configured restricted \`PTERO_API_KEY\`. Do not assume node/servers snapshots work until this key exists.

The planner uses a deterministic, independently validated mapping from the owner's requested ESN targets to those five allowlisted operations. Unsupported goals fail closed; there are **no model-authored shell commands or write actions**. This is a deliberate first phase for safety and reliability with the Qwen3 1.7B model.

## Reliability and safety

- Plans and each step are persisted in the existing protected Jarvis SQLite database. A maximum of five steps per plan and eight active/pending plans avoids runaway work.
- Approval is mandatory before **each new plan**, regardless of whether it was requested from Discord or the website.
- One worker runs one safe read-only step at a time. It records real results, retries a failed step at most once, and uses lease-based crash recovery so completed steps are not re-executed after restarts.
- Cancel is cooperative: it prevents additional steps from starting. An HTTP request already in flight may finish. Never claim an in-flight request was interrupted.
- Errors stored in the database are generic exception **types**, without provider response bodies or tokens.
- Owner login/session and CSRF checks guard the new API endpoints; Discord commands are ephemeral and owner-only. No passwords are stored in the plan.
- No browser scans because Chromium/Playwright was not installed. No arbitrary URLs, payment actions, DNS edits, Discord message broadcasts, Pterodactyl writes, server restarts, file editing, or CAPTCHA bypassing.
- Existing \`esnjarvis.slice\` limit remains **8 GiB of memory** and shared **2 CPU cores** for Jarvis web, Discord and Ollama. No new service, model or dependency is installed.

## Activation on the existing VPS

Pull the merged GitHub changes **as the esnjarvis service account**, run tests, then restart only Jarvis and Jarvis Discord:

\`\`\`bash
runuser -u esnjarvis -- git -C /opt/esn-jarvis/app pull --ff-only origin main &&
runuser -u esnjarvis -- sh -c 'cd /opt/esn-jarvis/app && /opt/esn-jarvis/venv/bin/python -m unittest discover -s tests -q' &&
systemctl restart esn-jarvis esn-jarvis-discord &&
systemctl is-active esn-jarvis esn-jarvis-discord
\`\`\`

Do **not** restart Wings, Docker, customer game servers or Nginx. Backup the existing database and configuration before major production upgrades. GitHub merge alone doesn't deploy this feature.

## Verification checklist

1. Discord \`/jarvis_auto\` gives a real plan ID, with status \`awaiting_approval\`; no steps execute.
2. Inspect the planned kinds and approve only if they match the requested read-only audit.
3. \`/jarvis_auto_status\` or Task Center shows actual queued/running/completed/failed steps with persistent results.
4. Repeat after restarting only Jarvis service: finished steps remain finished and new work proceeds.
5. Cancelling a queued plan prevents any operations from running.
6. Test an unsafe request (e.g. delete servers) and confirm Jarvis rejects it.
7. Verify \`systemctl show esn-jarvis esn-jarvis-discord -p Slice\` reports \`esnjarvis.slice\`.

**Next stage (not yet implemented):** AI-drafted plans from Qwen with strict policy validation, approval-gated staged GitHub/code/browser tools and richer tool results. Never treat generated text as permission to execute.
