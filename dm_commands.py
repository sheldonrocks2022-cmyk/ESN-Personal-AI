"""Owner-only text command fallback when Discord slash commands don't appear in DMs.

The Discord event listener checks the configured owner ID and a direct bot DM
before invoking this module. No shell, token extraction or production writes.
"""
import autonomous
import dm_access
import maintenance
import memory_store
import operations
import research
import managed_bots
import worker_budget
import local_model

PREFIX = "!jarvis "


def is_command(message):
    return isinstance(message, str) and message.lower().startswith(PREFIX)


def help_text():
    return (
        "Jarvis owner DM commands:\n"
        "!jarvis help | status | disk | capacity | ai | tasks | schedules\n"
        "!jarvis ask <question> | !jarvis search <query>\n"
        "!jarvis bots | bot <connection ID> | bot-send <connection ID> <channel ID> | <message>\n"
        "!jarvis panel nodes | panel servers (read-only)\n"
        "!jarvis check <task-kind>\n"
        "!jarvis remember <topic> | <note>  (use a vertical bar between topic and note)\n"
        "!jarvis memories | forget <topic>\n"
        "!jarvis auto <goal> | approve <plan UUID> | plan <plan UUID> | cancel <plan UUID>\n"
        "!jarvis grant <user ID> <minutes> [messages] | guests | revoke <user ID>\n"
        "Only your authorized bot DM can run these commands. Guest DMs remain chat-only."
    )


def _inventory(data, heading):
    items = data.get("items", [])
    if not isinstance(items, list):
        return "Unexpected Pterodactyl inventory."
    rows = [heading + " (first " + str(min(15,len(items))) + " of "
            + str(len(items)) + " in this API page):"]
    for item in items[:15]:
        rows.append(str(item.get("id", "?"))[:28] + " — "
                    + str(item.get("name", "unnamed")).replace("@", "")[:75])
    return "\n".join(rows)


def _plan(ident):
    p = autonomous.get(ident)
    lines = [p["status"] + ": " + str(p["completed_steps"]) + "/"
             + str(p["total_steps"]) + " steps finished"]
    lines += [str(s["position"] + 1) + ". " + s["kind"] + " — " + s["status"]
              for s in p["steps"]]
    lines.append("Verified results: https://jarvis.esnoffical.com/tasks")
    return "\n".join(lines)


def handle(message, *, owner_id=None):
    """Return a bounded response, never interpret provided text as code."""
    if not is_command(message):
        return None
    raw = message[len(PREFIX):].strip()
    if not raw or len(raw) > 1400:
        return help_text() if not raw else "Command is too long (limit 1400 characters)."
    name, _, arg = raw.partition(" ")
    name = name.casefold()
    arg = arg.strip()
    try:
        if name == "help":
            return help_text()
        if name == "status":
            import jarvis
            return "Panel HTTP status: " + str(jarvis.run_panel_job("panel_health")["http_status"])
        if name == "disk":
            d = maintenance.report()
            return ("Jarvis VPS only: %.2f GiB free (%.1f%%). Disk pressure: %s. "
                    "No files deleted and no remote nodes scanned." %
                    (d["free_bytes"]/1024**3, d["free_percent"], d["disk_pressure"]))
        if name == "capacity":
            with operations.conn() as db:
                d = worker_budget.snapshot(db)
            return ("Lightweight queue: %d/%d occupied; %d available. "
                    "Max %d active read-only check threads. "
                    "8 GiB limit verified: %s. Resource pause: %s." %
                    (d["occupied_slots"], d["queued_capacity"], d["available_slots"],
                     d["max_read_only_check_threads"], d["memory_slice_limit_active"],
                     d["memory_pressure_pauses_new_checks"]))
        if name == "ai":
            info = local_model.profile_status()
            return ("Jarvis local AI: " + info["fast_model"] + " / profile " + info["profile"] +
                    "; optional quality configured: " + str(info["quality_model_configured"]) +
                    ". No cloud API required. Models are not downloaded automatically.")
        if name == "ask" and arg:
            import jarvis
            return jarvis.chat(arg)[:1800]
        if name == "search" and arg:
            return research.format_results(research.search(arg))
        if name == "panel" and arg.lower() in ("nodes", "servers"):
            import jarvis
            kind = "nodes_snapshot" if arg.lower() == "nodes" else "servers_snapshot"
            return _inventory(jarvis.run_panel_job(kind), arg.title())
        if name == "bots":
            rows = managed_bots.list_bots()
            return "\n".join(r["label"] + " (" + r["id"] + ")" for r in rows) or "No managed bot tokens saved. Add them in Connections."
        if name == "bot" and arg:
            r = managed_bots.identity(arg)
            return "Authorized bot: " + r["bot_name"] + " (" + r["bot_id"] + ")."
        if name == "bot-send" and " | " in arg:
            first, content = arg.split(" | ", 1)
            parts = first.split()
            if len(parts) != 2:
                return "Use: !jarvis bot-send <connection ID> <guild channel ID> | <message>"
            result = managed_bots.send_one(parts[0], parts[1], content, confirm=True)
            return "Discord confirmed message ID " + result["message_id"] + " in channel " + result["channel_id"]
        if name == "tasks":
            records = operations.jobs()[:10]
            return "\n".join(x["kind"] + ": " + x["status"] + " ID " + x["id"] for x in records) or "No tasks."
        if name == "schedules":
            records = operations.schedules()[:10]
            return "\n".join(x["kind"] + ": every " + str(x["interval_minutes"]) +
                              " minutes; " + ("active" if x["enabled"] else "paused")
                              for x in records) or "No schedules."
        if name == "check" and arg:
            if arg not in operations.TASK_KINDS or arg == "browser_scan":
                return "Unsupported or unavailable task kind. Browser scans need an isolated browser worker."
            ident = operations.enqueue(arg, {})
            return "Queued read-only " + arg + " job ID " + ident + ". This is not complete yet."
        if name == "remember" and " | " in arg:
            import jarvis
            topic, note = arg.split(" | ", 1)
            return "Encrypted memory saved: " + memory_store.remember(jarvis.DB_PATH, topic, note)
        if name == "memories":
            import jarvis
            notes = memory_store.list_notes(jarvis.DB_PATH, 15)
            return "\n".join(x["topic"] + ": " + x["note"] for x in notes) or "No saved memories."
        if name == "forget" and arg:
            import jarvis
            return "Memory deleted." if memory_store.forget(jarvis.DB_PATH, arg) else "No matching memory."
        if name == "auto" and arg:
            ident = autonomous.create(arg)
            plan = autonomous.get(ident)
            rows = ["Approval needed. Plan ID: " + ident]
            rows += [str(x["position"] + 1) + ". " + x["kind"] for x in plan["steps"]]
            rows.append("To start: !jarvis approve " + ident)
            return "\n".join(rows)
        if name == "approve" and arg:
            autonomous.approve(arg)
            return "Read-only plan approved. View progress with !jarvis plan <plan ID>."
        if name == "plan" and arg:
            return _plan(arg)
        if name == "cancel" and arg:
            return "Plan state: " + autonomous.cancel(arg)
        if name == "grant" and arg:
            parts = arg.split()
            if len(parts) not in (2, 3):
                return "Use: !jarvis grant <user ID> <minutes> [message allowance]"
            uid = dm_access.validate_user_id(parts[0])
            if owner_id is not None and int(uid) == int(owner_id):
                return "Owner already has full access."
            d = dm_access.grant(uid, int(parts[1]), int(parts[2]) if len(parts) == 3 else 12)
            return ("Guest " + uid + " approved until <t:" + str(d["expires_at"]) +
                    ":R> with " + str(d["remaining"]) + " general questions only.")
        if name == "guests":
            rows = dm_access.active_grants()
            return "\n".join(x["user_id"] + ": " + str(x["remaining"]) +
                              " left; expires <t:" + str(x["expires_at"]) + ":R>"
                              for x in rows) or "No active guest grants."
        if name == "revoke" and arg:
            return "Guest revoked." if dm_access.revoke(arg) else "No matching grant."
        return "Unknown command. Send !jarvis help."
    except (ValueError, KeyError, TypeError):
        return "Invalid command arguments. Send !jarvis help."
    except RuntimeError as error:
        if "Web search is not configured" in str(error):
            return "Web search requires an owner-configured Brave Search API key."
        if "PTERO_API_KEY is not configured" in str(error):
            return "Pterodactyl API credentials have not been configured."
        return "Jarvis command unavailable. Check private server logs."
    except Exception:
        return "Jarvis command failed. Check private server logs."
