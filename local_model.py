"""Local-only Ollama chat adapter for ESN Jarvis.

Ollama is contacted exclusively on IPv4 loopback; it is never exposed through
Nginx or contacted using arbitrary user-supplied URLs.
"""
import json
import os
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_MODELS_CACHE = {"expires": 0.0, "installed": ()}
_MODELS_LOCK = threading.Lock()
_COMPLEX = re.compile(
    r"\b(code|coding|python|javascript|java|typescript|rust|debug|"
    r"program|design|architecture|optimi[sz]|reason|analy[sz]|"
    r"refactor|algorithm|security|explain why|plan a)\b", re.I
)


def profile_status():
    mode = os.environ.get("ESN_AI_PROFILE", "efficient").strip().lower()
    if mode not in ("efficient", "adaptive", "quality"):
        mode = "efficient"
    return {
        "profile": mode,
        "fast_model": os.environ.get("OLLAMA_MODEL", "qwen3:1.7b"),
        "quality_model_configured": bool(os.environ.get("OLLAMA_MODEL_QUALITY")),
        "max_loaded_models_expected": 1,
        "local_only": True,
        "model_downloads_automatic": False,
        "note": "The optional quality model must be installed explicitly, benchmarked, and fit the shared 8 GiB slice. Fast model is always the fallback.",
    }


def _installed(model):
    # Do not automatically download unverified models or fetch external URLs.
    stamp = time.monotonic()
    with _MODELS_LOCK:
        if stamp >= _MODELS_CACHE["expires"]:
            names = []
            req = Request("http://127.0.0.1:11434/api/tags", method="GET")
            try:
                with urlopen(req, timeout=3) as response:
                    raw = json.loads(response.read(262144))
                if isinstance(raw, dict):
                    names = [x.get("name", "") for x in raw.get("models", [])[:50]
                             if isinstance(x, dict)]
            except Exception:
                names = []
            _MODELS_CACHE["installed"] = tuple(names)
            _MODELS_CACHE["expires"] = stamp + 60
        return model in _MODELS_CACHE["installed"]


def _select_model(messages, tools):
    fast = os.environ.get("OLLAMA_MODEL", "qwen3:1.7b")
    mode = profile_status()["profile"]
    quality = os.environ.get("OLLAMA_MODEL_QUALITY", "").strip()
    if mode == "efficient" or not tools or not quality or quality == fast:
        return fast
    if mode == "adaptive":
        question = str(next(
            (msg.get("content", "") for msg in reversed(messages)
             if isinstance(msg, dict) and msg.get("role") == "user"), ""
        ))[:4000]
        if not _COMPLEX.search(question):
            return fast
    import resources
    snapshot = resources.snapshot()
    # Never load a larger optional model unless the resource ceiling is proven.
    if not snapshot.get("shared_cap_active") or snapshot.get("used_bytes") is None:
        return fast
    high = snapshot.get("throttle_above_bytes") or 7 * 1024**3
    if snapshot["used_bytes"] >= high - 2 * 1024**3:
        return fast
    if _installed(quality):
        return quality
    return fast


def chat(messages, tools):
    model = _select_model(messages, tools)
    if not isinstance(model, str) or not (1 <= len(model) <= 80) or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for c in model):
        raise RuntimeError("Invalid local model name")
    if not isinstance(messages, list) or not isinstance(tools, list):
        raise RuntimeError("Invalid model request")
    # Small, bounded requests make this safer for an ESN Wings host.
    payload = {
        "model": model, "messages": messages, "tools": tools,
        "stream": False, "think": False, "keep_alive": 0,
        "options": {"num_ctx": 4096, "num_predict": 512},
    }
    req = Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urlopen(req, timeout=120) as response:
            result = json.loads(response.read(1024 * 1024))
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        # No arbitrary upstream response body or secrets in error output.
        raise RuntimeError("Local Ollama service unavailable or returned an invalid response") from exc
    message = result.get("message") if isinstance(result, dict) else None
    if not isinstance(message, dict):
        raise RuntimeError("Local model did not return a message")
    # Ollama encodes tool arguments as objects; the existing validated executor
    # expects JSON strings and OpenAI-compatible type=function descriptors.
    calls = message.get("tool_calls") or []
    if not isinstance(calls, list) or len(calls) > 3:
        raise RuntimeError("Invalid local model tool calls")
    normalized = []
    for call in calls:
        fn = call.get("function") if isinstance(call, dict) else None
        if not isinstance(fn, dict):
            raise RuntimeError("Invalid local model tool call")
        args = fn.get("arguments", {})
        if not isinstance(args, (dict, str)):
            raise RuntimeError("Invalid local tool arguments")
        normalized.append({"type": "function", "function": {
            "name": fn.get("name"),
            "arguments": json.dumps(args) if isinstance(args, dict) else args,
        }})
    content = message.get("content") or ""
    if not isinstance(content, str):
        raise RuntimeError("Invalid local model content")
    return {"content": content, "tool_calls": normalized}
