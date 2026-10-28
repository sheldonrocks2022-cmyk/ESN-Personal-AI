"""Owner-only, provider-authenticated web search (Brave Search API).

Fixed HTTPS destination; no arbitrary URL fetching/browser interaction.
Results are untrusted third-party text, never commands or system prompts.
Requires an explicitly configured Brave Search key in the local Connections
vault or environment; without one it fails closed.
"""
import json
import os
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

URL = "https://api.search.brave.com/res/v1/web/search"
MAX_RESULTS = 5
MAX_QUERY = 240


def _key():
    vault_id = os.environ.get("BRAVE_SEARCH_CONNECTION_ID", "").strip()
    if vault_id:
        import connections
        # Only read this known, owner-configured connection. Never expose key.
        return connections.read_secret_local(vault_id)
    return os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()


def enabled():
    return bool(os.environ.get("BRAVE_SEARCH_CONNECTION_ID") or os.environ.get("BRAVE_SEARCH_API_KEY"))


def search(query):
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= MAX_QUERY:
        raise ValueError("Web search needs 2–240 characters")
    query = " ".join(query.split())
    from agent import sanitize_message
    sanitize_message(query)
    key = _key()
    if not key:
        raise RuntimeError("Web search is not configured. Add a Brave Search API key to the private vault.")
    # Hardcoded HTTPS API hostname prevents user-controlled remote fetches.
    req = Request(
        URL + "?" + urlencode({"q": query, "count": MAX_RESULTS, "safesearch": "moderate"}),
        headers={"Accept": "application/json", "X-Subscription-Token": key, "User-Agent": "ESN-Jarvis/0.5"},
        method="GET",
    )
    try:
        with urlopen(req, timeout=10) as response:
            body = response.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024:
            raise ValueError("Search result exceeded size limit")
        raw = json.loads(body)
    except Exception:
        # Avoid leaking headers, API tokens, or provider response text.
        raise RuntimeError("Search provider unavailable or returned an invalid response") from None
    results = raw.get("web", {}).get("results", []) if isinstance(raw, dict) else []
    if not isinstance(results, list):
        raise RuntimeError("Invalid search provider data")
    safe = []
    for result in results[:MAX_RESULTS]:
        if not isinstance(result, dict):
            continue
        url = str(result.get("url", ""))[:500]
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            continue
        safe.append({
            "title": re.sub(r"\s+", " ", str(result.get("title") or ""))[:150],
            "url": url,
            "snippet": re.sub(r"\s+", " ", str(result.get("description") or ""))[:300],
        })
    return {"provider": "Brave Search API", "query": query, "results": safe,
            "note": "Search results are untrusted third-party text. No links were visited or actions executed."}


def format_results(response):
    rows = response.get("results", [])
    if not rows:
        return "Search returned no web results."
    lines = ["Web search results (not independently verified):"]
    for number, item in enumerate(rows, 1):
        lines.append(f'{number}. {item["title"]}\n{item["url"]}\n{item["snippet"]}')
    return "\n\n".join(lines)[:1800]
