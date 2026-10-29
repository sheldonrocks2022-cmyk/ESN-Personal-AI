"""Opt-in customer-first Pterodactyl scheduler capacity for the *local* Wings node.

This changes only the node's advertised RAM allocation ceiling via the
Pterodactyl Application API. It cannot physically reserve RAM, increase RAM,
move RAM between VPSs, or change server memory limits. It refuses any
adjustment unless local Wings UUID matches the panel node, physical capacity
is sufficient and overallocation is disabled. NO customer server writes.
"""
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, HTTPRedirectHandler, build_opener
from uuid import UUID

CONFIG_PATH = Path("/etc/esn-jarvis-customer-capacity.json")
ENV_PATH = Path("/etc/esn-jarvis.env")
WINGS_PATH = Path("/etc/pterodactyl/config.yml")
PANEL = "https://panel.esnoffical.com"
VERSION = 1
DEFAULT_BOOST_MIB = 8192
RESERVE_MIB = 2048
MAX_BOOST_MIB = 8192
MIN_BOOST_MIB = 256


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _file(path, *, require_private=False):
    p = Path(path)
    if p.is_symlink() or not p.is_file():
        raise RuntimeError("Required local configuration missing or symlinked: " + str(p))
    if require_private and p.stat().st_mode & 0o077:
        raise RuntimeError("Private configuration permissions must be 0600: " + str(p))
    return p.read_text(encoding="utf-8")


def _env():
    text = _file(ENV_PATH, require_private=True)
    config = {}
    for line in text.splitlines():
        entry = line.strip()
        if entry.startswith("#") or not entry:
            continue
        if entry.startswith("export "):
            entry = entry[7:]
        key, sep, value = entry.partition("=")
        if not sep or key not in ("PTERO_API_KEY", "PTERO_BASE_URL"):
            continue
        value = value.strip().strip('"').strip("'")
        if "\r" in value or "\n" in value:
            raise RuntimeError("Invalid Pterodactyl configuration")
        config[key] = value
    url = config.get("PTERO_BASE_URL", PANEL).rstrip("/")
    if url != PANEL:
        raise RuntimeError("Refusing a panel URL other than the configured official ESN panel")
    key = config.get("PTERO_API_KEY", "")
    if not key or len(key) > 1000 or any(c.isspace() for c in key):
        raise RuntimeError("PTERO_API_KEY must be set privately in /etc/esn-jarvis.env")
    return key


def _wings_uuid():
    text = _file(WINGS_PATH)
    match = re.search(r"^uuid:\s*['\"]?([0-9a-fA-F-]{36})['\"]?\s*$", text, re.M)
    if not match:
        raise RuntimeError("No Wings UUID on this VPS; cannot assign another node's RAM")
    try:
        return str(UUID(match.group(1)))
    except ValueError as exc:
        raise RuntimeError("Invalid local Wings UUID") from exc


def _node_update_body(path, memory):
    """Preserve all editable node settings required by the panel API.

    Pterodactyl node update validators commonly require all main node fields
    even on PATCH. A memory-only body can fail HTTP 422, or risk resetting
    unrelated settings on nonstandard panel versions.
    """
    if type(memory) is not int or memory <= 0 or memory > 262144:
        raise RuntimeError("Requested node RAM limit must be a finite positive MiB value")
    data = _api(path)  # read again immediately before the write
    node = _attributes(data)
    try:
        ident = int(path.rsplit("/", 1)[-1])
    except ValueError:
        raise RuntimeError("Invalid Pterodactyl node update target") from None
    if node["id"] != ident or node["memory_overallocate"] != 0:
        raise RuntimeError("Node identity or overallocation changed; refusing RAM update")
    fields = ("name", "location_id", "fqdn", "scheme",
              "memory_overallocate", "disk", "disk_overallocate",
              "daemon_listen", "daemon_sftp")
    result = {}
    for field in fields:
        value = node.get(field)
        if field in ("name", "fqdn", "scheme"):
            if not isinstance(value, str) or not value:
                raise RuntimeError("Missing verified Pterodactyl field: " + field)
        elif type(value) is not int:
            raise RuntimeError("Missing verified Pterodactyl field: " + field)
        result[field] = value
    result["memory"] = memory
    for field in ("description", "behind_proxy", "maintenance_mode",
                  "upload_size", "daemon_base"):
        if field in node:
            value = node[field]
            if field in ("behind_proxy", "maintenance_mode") and type(value) is not bool:
                raise RuntimeError("Invalid node option: " + field)
            if field == "upload_size" and type(value) is not int:
                raise RuntimeError("Invalid node option: " + field)
            if field == "daemon_base" and (not isinstance(value, str) or not value):
                raise RuntimeError("Invalid node option: " + field)
            if field == "description" and value is not None and not isinstance(value, str):
                raise RuntimeError("Invalid node option: " + field)
            result[field] = value
    return result


def _api(path, *, memory=None):
    """Fixed HTTPS API; no redirects that could disclose the admin token."""
    if not re.fullmatch(r"/api/application/nodes(?:\\?per_page=100&page=[123]|/[0-9]{1,8})", path):
        raise ValueError("Unsupported panel API path")
    key = _env()
    body = _node_update_body(path, memory) if memory is not None else None
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = Request(PANEL + path, data=data, method="PATCH" if data else "GET", headers={
        "Authorization": "Bearer " + key,
        "Accept": "Application/vnd.pterodactyl.v1+json",
        "Content-Type": "application/json",
        "User-Agent": "ESN-Jarvis-CustomerCapacity/0.1",
    })
    try:
        with build_opener(NoRedirect()).open(req, timeout=12) as response:
            if response.status != 200:
                raise RuntimeError("Unexpected Pterodactyl response status")
            raw = response.read(262145)
    except HTTPError as exc:
        raise RuntimeError("Pterodactyl Application API HTTP " + str(exc.code)) from None
    except (URLError, OSError, TimeoutError):
        raise RuntimeError("Could not contact Pterodactyl Application API") from None
    if len(raw) > 262144:
        raise RuntimeError("Pterodactyl response too large")
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("Invalid Pterodactyl response") from exc
    if not isinstance(obj, dict):
        raise RuntimeError("Invalid Pterodactyl response")
    return obj


def _attributes(payload):
    attrs = payload.get("attributes")
    if not isinstance(attrs, dict):
        raise RuntimeError("Missing node attributes from panel")
    if not isinstance(attrs.get("id"), int) or isinstance(attrs["id"], bool):
        raise RuntimeError("Missing Pterodactyl node ID")
    for k in ("memory", "memory_overallocate"):
        if type(attrs.get(k)) is not int:
            raise RuntimeError("Missing verified node " + k)
    allocated = attrs.get("allocated_resources")
    if not isinstance(allocated, dict) or type(allocated.get("memory")) is not int:
        raise RuntimeError("Panel did not provide allocated customer RAM; refusing")
    try:
        attrs["uuid"] = str(UUID(str(attrs["uuid"])))
    except (KeyError, ValueError):
        raise RuntimeError("Panel node UUID missing or invalid") from None
    if attrs["memory"] <= 0 or allocated["memory"] < 0:
        raise RuntimeError("Invalid node memory accounting")
    return attrs


def _local_node():
    local = _wings_uuid()
    matched = []
    for page in range(1, 4):
        payload = _api("/api/application/nodes?per_page=100&page=" + str(page))
        entries = payload.get("data")
        if not isinstance(entries, list):
            raise RuntimeError("Invalid Pterodactyl nodes listing")
        for item in entries:
            if not isinstance(item, dict) or not isinstance(item.get("attributes"), dict):
                continue
            candidate = item["attributes"]
            if str(candidate.get("uuid", "")).lower() == local:
                matched.append(_attributes(item))
        pages = payload.get("meta", {}).get("pagination", {}).get("total_pages", 1)
        if type(pages) is not int or pages > 3:
            raise RuntimeError("Node inventory too large or missing pagination assurance")
        if page >= pages:
            break
    if len(matched) != 1:
        raise RuntimeError("This VPS's Wings UUID does not uniquely match an ESN Panel node")
    return matched[0]


def _node(ident, expected_uuid):
    if type(ident) is not int or not 1 <= ident <= 99999999:
        raise RuntimeError("Invalid configured local node ID")
    attrs = _attributes(_api("/api/application/nodes/" + str(ident)))
    if attrs["id"] != ident or attrs["uuid"] != expected_uuid or _wings_uuid() != expected_uuid:
        raise RuntimeError("Local Wings and configured Pterodactyl node identity mismatch")
    return attrs


def _total_mib():
    try:
        match = re.search(r"^MemTotal:\s*(\d+)\s+kB$", Path("/proc/meminfo").read_text(), re.M)
        if not match:
            raise ValueError("Missing MemTotal")
        return int(match.group(1)) // 1024
    except (OSError, ValueError):
        raise RuntimeError("Host physical RAM total unavailable") from None


def _available_mib():
    try:
        match = re.search(r"^MemAvailable:\s*(\d+)\s+kB$", Path("/proc/meminfo").read_text(), re.M)
        if not match:
            raise ValueError("Missing MemAvailable")
        return int(match.group(1)) // 1024
    except (OSError, ValueError):
        raise RuntimeError("Host available RAM unavailable") from None


def _ensure_capacity(node, boost_mib, reserve_mib=RESERVE_MIB):
    if type(boost_mib) is not int or not MIN_BOOST_MIB <= boost_mib <= MAX_BOOST_MIB:
        raise RuntimeError("Boost must be 256–8192 MiB")
    if type(reserve_mib) is not int or reserve_mib < 2048:
        raise RuntimeError("Host OS reserve cannot be less than 2048 MiB")
    if node["memory_overallocate"] != 0:
        raise RuntimeError("Node has RAM overallocation enabled; refusing capacity boost")
    before = node["memory"]
    customer = node["allocated_resources"]["memory"]
    if customer > before:
        raise RuntimeError("Node is already overallocated; refusing customer boost")
    after = before + boost_mib
    total = _total_mib()
    if after > total - reserve_mib:
        safe = max(0, total - reserve_mib - before)
        raise RuntimeError("Insufficient physical RAM for 8 GiB boost. "
                           "Current safe headroom above node allocation is " +
                           str(safe) + " MiB; use a smaller --boost-mib only if appropriate")
    return {"node_id": node["id"], "uuid": node["uuid"], "base_mib": before,
            "extra_mib": boost_mib, "target_mib": after,
            "reserve_mib": reserve_mib, "physical_mib": total,
            "allocated_mib": customer}


def _validate_config(data):
    if not isinstance(data, dict) or data.get("version") != VERSION:
        raise RuntimeError("Invalid customer capacity configuration")
    if set(data) != {"version", "node_id", "uuid", "base_mib", "extra_mib",
                     "target_mib", "reserve_mib", "physical_mib", "allocated_mib"}:
        raise RuntimeError("Invalid customer capacity configuration fields")
    if type(data["node_id"]) is not int or not 1 <= data["node_id"] <= 99999999:
        raise RuntimeError("Invalid node ID")
    try:
        if str(UUID(data["uuid"])) != data["uuid"]:
            raise ValueError("Bad UUID")
    except (TypeError, ValueError):
        raise RuntimeError("Invalid node UUID") from None
    for field in ("base_mib", "extra_mib", "target_mib", "reserve_mib", "physical_mib", "allocated_mib"):
        if type(data[field]) is not int or data[field] < 0:
            raise RuntimeError("Invalid capacity accounting")
    if not MIN_BOOST_MIB <= data["extra_mib"] <= MAX_BOOST_MIB:
        raise RuntimeError("Invalid customer boost")
    if data["target_mib"] != data["base_mib"] + data["extra_mib"]:
        raise RuntimeError("Inconsistent node capacity settings")
    if data["target_mib"] > data["physical_mib"] - data["reserve_mib"]:
        raise RuntimeError("Capacity would exceed known physical RAM")
    return data


def config():
    if not CONFIG_PATH.exists() and not CONFIG_PATH.is_symlink():
        return None
    try:
        return _validate_config(json.loads(_file(CONFIG_PATH, require_private=True)))
    except (ValueError, UnicodeError) as exc:
        raise RuntimeError("Invalid customer capacity configuration") from exc


def _write_private(path, data):
    if path.is_symlink():
        raise RuntimeError("Refusing symlinked capacity config")
    if path.exists():
        raise RuntimeError("Capacity config already exists; cannot overwrite")
    p = Path(path)
    if p.parent.is_symlink():
        raise RuntimeError("Unsafe capacity configuration parent")
    fd, name = tempfile.mkstemp(prefix=".capacity-", dir=str(p.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(data, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if p.exists() or p.is_symlink():
            raise RuntimeError("Capacity config appeared concurrently; refusing overwrite")
        os.link(name, p)
    finally:
        Path(name).unlink(missing_ok=True)


def plan_safe_limits(boost_mib=DEFAULT_BOOST_MIB, reserve_mib=4096):
    """READ-ONLY planning for a wildly oversized node limit.

    Never writes the node. Proposes a finite ON/OFF scheduler ceiling where
    customer allocations fit the ON value and the OFF ceiling is at most
    physical RAM minus a conservative OS/software reserve.
    """
    if type(boost_mib) is not int or not MIN_BOOST_MIB <= boost_mib <= MAX_BOOST_MIB:
        raise RuntimeError("Requested customer boost must be 256–8192 MiB")
    if type(reserve_mib) is not int or reserve_mib < 4096:
        raise RuntimeError("Read-only planner requires at least 4096 MiB OS reserve")
    node = _local_node()
    if node["memory_overallocate"] != 0:
        raise RuntimeError("RAM overallocation must be zero before planning")
    physical = _total_mib()
    customer_allocated = node["allocated_resources"]["memory"]
    # Round down to GiB boundaries to avoid advertising partial reserve RAM.
    off = ((physical - reserve_mib) // 1024) * 1024
    on = off - boost_mib
    if off <= 0 or on <= 0 or customer_allocated > on:
        raise RuntimeError(
            "Customer RAM allocations do not fit an 8 GiB ON/OFF swap "
            "with a minimum 4 GiB host reserve. Do not reduce existing allocations."
        )
    return {
        "node_id": node["id"],
        "node_uuid": node["uuid"],
        "existing_node_mib": node["memory"],
        "physical_mib": physical,
        "customer_allocated_mib": customer_allocated,
        "suggested_on_mib": on,
        "suggested_off_mib": off,
        "extra_customer_off_mib": boost_mib,
        "remaining_host_off_mib": physical - off,
        "current_node_is_oversized": node["memory"] > physical - reserve_mib,
    }


def print_safe_plan(boost_mib=DEFAULT_BOOST_MIB):
    proposal = plan_safe_limits(boost_mib)
    print("READ-ONLY CUSTOMER CAPACITY PLAN — NO CHANGES MADE")
    print("Verified local Wings node ID:", proposal["node_id"])
    print("Physical host RAM:", proposal["physical_mib"], "MiB")
    print("Currently allocated to customer servers:",
          proposal["customer_allocated_mib"], "MiB")
    print("Currently advertised in Pterodactyl:",
          proposal["existing_node_mib"], "MiB")
    print("Suggested Jarvis ON node limit:", proposal["suggested_on_mib"], "MiB")
    print("Suggested Jarvis OFF node limit:", proposal["suggested_off_mib"], "MiB")
    print("Additional customer allocation allowance when Jarvis OFF:",
          proposal["extra_customer_off_mib"], "MiB")
    print("RAM outside the OFF customer limit for Linux/other services:",
          proposal["remaining_host_off_mib"], "MiB")
    if proposal["current_node_is_oversized"]:
        print("WARNING: panel node limit is larger than safe physical RAM.")
        print("DO NOT run 'esnjarvis customers enable' yet; it cannot use this huge baseline.")
        print("Owner must separately approve a finite node-limit correction before enabling automatic switching.")
    else:
        print("Check existing customer allocations and node policy before enabling any switching.")
    print("No panel API writes; no service stop; no customer server changes.")
    return proposal


def preflight(boost_mib=DEFAULT_BOOST_MIB):
    node = _local_node()
    return _ensure_capacity(node, boost_mib)


def check(boost_mib=DEFAULT_BOOST_MIB):
    current = config()
    if current:
        node = _node(current["node_id"], current["uuid"])
        print("Customer-first mode: ENABLED for local Wings node " + str(node["id"]))
        print("Configured baseline: %d MiB; OFF target: %d MiB; boost: %d MiB" %
              (current["base_mib"], current["target_mib"], current["extra_mib"]))
        print("Current panel node: %d MiB; customer server allocations: %d MiB" %
              (node["memory"], node["allocated_resources"]["memory"]))
        if node["memory"] not in (current["base_mib"], current["target_mib"]):
            print("WARNING: panel memory changed externally; automatic transitions will refuse.")
        return current
    plan = preflight(boost_mib)
    print("Customer-first mode: DISABLED (read-only preview)")
    print("Local Wings node %d; physical RAM %d MiB; node memory %d MiB; already allocated %d MiB" %
          (plan["node_id"], plan["physical_mib"], plan["base_mib"], plan["allocated_mib"]))
    print("Proposed OFF allocation: %d MiB (extra %d MiB); leave %d MiB for host OS" %
          (plan["target_mib"], plan["extra_mib"], plan["reserve_mib"]))
    print("No panel mutation or customer server allocation has occurred.")
    return plan


def enable(boost_mib=DEFAULT_BOOST_MIB):
    if config():
        raise RuntimeError("Customer capacity mode already configured")
    plan = preflight(boost_mib)
    obj = {"version": VERSION, **plan}
    _write_private(CONFIG_PATH, obj)
    print("Customer-first mode ENABLED for future Jarvis OFF/ON transitions.")
    print("No panel settings changed now. Next 'esnjarvis off' will apply verified boost.")
    return obj


def disable(*, power_off_record_exists=False):
    if power_off_record_exists:
        raise RuntimeError("Cannot disable customer mode while Jarvis is OFF")
    current = config()
    if current is None:
        print("Customer-first mode already disabled.")
        return
    node = _node(current["node_id"], current["uuid"])
    if node["memory"] != current["base_mib"]:
        raise RuntimeError("Panel node not at baseline; cannot disable with a boosted allocation")
    CONFIG_PATH.unlink()
    print("Customer-first mode disabled; panel remains unchanged.")


def off_preflight(current):
    """Call before any Jarvis service stops. No mutation."""
    node = _node(current["node_id"], current["uuid"])
    if node["memory"] != current["base_mib"] or node["memory_overallocate"] != 0:
        raise RuntimeError("Panel node differs from expected baseline; refusing Jarvis OFF transition")
    if node["allocated_resources"]["memory"] > current["base_mib"]:
        raise RuntimeError("Existing customer allocations already exceed baseline")
    if current["target_mib"] > _total_mib() - current["reserve_mib"]:
        raise RuntimeError("Host RAM changed; planned boost is no longer safe")
    return current


def _patch(node_id, memory, expected_uuid):
    before = _node(node_id, expected_uuid)
    if before["memory_overallocate"] != 0:
        raise RuntimeError("Memory overallocation unexpectedly enabled; refusing update")
    response = _attributes(_api("/api/application/nodes/" + str(node_id), memory=memory))
    if response["id"] != node_id or response["uuid"] != expected_uuid:
        raise RuntimeError("Panel update returned unexpected node identity")
    if response["memory"] != memory:
        raise RuntimeError("Panel did not confirm requested node memory")
    return response


def apply_off(current):
    """Call only after ALL chosen Jarvis services are inactive.

    Rechecking immediately before PATCH prevents resuming a half-complete
    transition with stale customer allocation and node settings.
    """
    node = _node(current["node_id"], current["uuid"])
    if node["memory"] == current["target_mib"]:
        if node["allocated_resources"]["memory"] > current["target_mib"]:
            raise RuntimeError("Customer allocations exceed OFF target")
        return False
    off_preflight(current)
    _patch(current["node_id"], current["target_mib"], current["uuid"])
    node = _node(current["node_id"], current["uuid"])
    if node["memory"] != current["target_mib"]:
        raise RuntimeError("Panel boost could not be verified")
    return True


def restore_on(current):
    """Restore customer scheduling cap BEFORE Jarvis can restart.

    If someone has provisioned servers against the 8 GiB boost, refuse ON
    rather than taking customer's potential RAM.
    """
    node = _node(current["node_id"], current["uuid"])
    if node["memory_overallocate"] != 0:
        raise RuntimeError("Cannot restore: Pterodactyl memory overallocation is enabled")
    if node["allocated_resources"]["memory"] > current["base_mib"]:
        raise RuntimeError(
            "Jarvis stays OFF: customer server RAM allocations exceed the original "
            "node budget. Move/reduce authorized customer allocations or keep Jarvis OFF."
        )
    if node["memory"] not in (current["base_mib"], current["target_mib"]):
        raise RuntimeError("Panel node memory changed externally; refusing Jarvis restart")
    if _available_mib() < current["extra_mib"] + current["reserve_mib"]:
        raise RuntimeError("Jarvis stays OFF: insufficient actual free host RAM for its 8 GiB budget")
    if node["memory"] == current["target_mib"]:
        _patch(current["node_id"], current["base_mib"], current["uuid"])
    check = _node(current["node_id"], current["uuid"])
    if check["memory"] != current["base_mib"] or check["allocated_resources"]["memory"] > current["base_mib"]:
        raise RuntimeError("Could not verify safe customer allocation cap; Jarvis remains OFF")
    return True
