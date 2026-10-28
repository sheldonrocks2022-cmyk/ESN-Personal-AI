"""Owner-scoped ESN Jarvis Search REST API.

A caller may authenticate with an existing owner browser session + CSRF,
or with an independent search-only Bearer key ESN_SEARCH_API_TOKEN.
This key cannot access any other Jarvis API. No cross-origin CORS.
"""
import hmac
import os
import threading
import time
from urllib.parse import urlsplit
import connections
import research

RATE_WINDOW = 60
RATE_LIMIT = 20
_RESTRICTIONS = {}
_LOCK = threading.Lock()


def _search_token(handler):
    supplied = handler.headers.get("Authorization", "")
    key = os.environ.get("ESN_SEARCH_API_TOKEN", "")
    return bool(len(key) >= 32 and
                hmac.compare_digest(supplied, "Bearer " + key))


def _authorize(handler):
    if _search_token(handler):
        return True
    token = connections.token_from_cookie(handler.headers.get("Cookie", ""))
    return connections.session_valid(token)


def _csrf(handler):
    if _search_token(handler):
        return True
    token = connections.token_from_cookie(handler.headers.get("Cookie", ""))
    return (
        connections.session_valid(token)
        and handler.headers.get("Origin", "") == connections.PUBLIC_ORIGIN
        and hmac.compare_digest(handler.headers.get("X-ESN-CSRF", ""),
                                connections.csrf_token(token))
    )


def _budget(identity):
    stamp = time.monotonic()
    with _LOCK:
        cutoff = stamp - RATE_WINDOW
        # Bound state growth, not user-visible output.
        for k in list(_RESTRICTIONS):
            _RESTRICTIONS[k] = [s for s in _RESTRICTIONS[k] if s > cutoff]
            if not _RESTRICTIONS[k]:
                del _RESTRICTIONS[k]
        previous = _RESTRICTIONS.get(identity, [])
        if len(previous) >= RATE_LIMIT:
            return False
        _RESTRICTIONS[identity] = previous + [stamp]
        return True


def handle(handler):
    path = urlsplit(handler.path).path
    if path not in ("/api/search", "/api/search/status"):
        return False
    if not _authorize(handler):
        handler.send_json(401, {"error": "Search requires owner login or a scoped search API key"})
        return True
    if path == "/api/search/status" and handler.command == "GET":
        handler.send_json(200, {
            "ready": research.enabled(),
            "backend": research.backend(),
            "max_results": research.MAX_RESULTS,
            "private_api": True,
            "api_key_scoped_to_search_only": True,
        })
        return True
    if handler.command != "POST":
        handler.send_json(405, {"error": "Use POST /api/search for a query"})
        return True
    if not _csrf(handler):
        handler.send_json(403, {"error": "Invalid origin or CSRF"})
        return True
    # All requests, including rejected inputs, count toward the low-cost search quota.
    identity = ("api" if _search_token(handler) else
                "browser:" + connections.token_from_cookie(handler.headers.get("Cookie", ""))[:24])
    if not _budget(identity):
        handler.send_json(429, {"error": "Search rate limit; retry after one minute"})
        return True
    try:
        body = connections.read_json(handler)
        if set(body) != {"query"}:
            raise ValueError("Only the search query field is permitted")
        result = research.search(body["query"])
        handler.send_json(200, result)
    except (TypeError, ValueError):
        handler.send_json(400, {"error": "Use a valid 2–240 character search query"})
    except RuntimeError:
        handler.send_json(503, {"error": "Search backend not configured or temporarily unavailable"})
    return True
