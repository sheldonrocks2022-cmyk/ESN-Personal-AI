"""Local-only Ollama chat adapter for ESN Jarvis.

Ollama is contacted exclusively on IPv4 loopback; it is never exposed through
Nginx or contacted using arbitrary user-supplied URLs.
"""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def chat(messages, tools):
    model = os.environ.get("OLLAMA_MODEL", "qwen3:1.7b")
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
