"""A minimal *real* natural-language-to-tool bridge for safe ESN tasks.

Only the function schema below can be called by the model; the executor
validates the arguments again and enqueues read-only, auditable tasks.
It is NOT an unrestricted coding agent or a shell/browser controller.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
import hmac
import connections
import operations

TOOLS = [{
    'type': 'function',
    'function': {
        'name': 'queue_esn_check',
        'description': 'Request a real read-only ESN infrastructure or public website check. Returns a job ID; do not claim the check completed.',
        'parameters': {
            'type': 'object',
            'properties': {
                'kind': {'type': 'string', 'enum': sorted(operations.TASK_KINDS)},
                'target': {'type': 'string', 'enum': ['website', 'panel'], 'description': 'Required only if kind is browser_scan.'},
            },
            'required': ['kind'],
            'additionalProperties': False,
        },
    },
}]
MAX_CALLS = 3


def sanitize_message(value):
    if not isinstance(value, str) or not (1 <= len(value) <= 4000):
        raise ValueError('Message must be between 1 and 4000 characters')
    # Avoid sending recognizable access credentials to external models.
    if re.search(r'(?i)(?:sk-[A-Za-z0-9_-]{12,}|ptla_[A-Za-z0-9_-]{10,}|mfa\.[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9_-]{10,})', value):
        raise ValueError('Message appears to contain an API token; save credentials in Connections, not chat')
    return value


def respond_to_tool_calls(message, enqueue=None):
    """Process only recognized model tools; never trust the model's claimed success."""
    if enqueue is None:
        enqueue = operations.enqueue
    if not isinstance(message, dict):
        raise RuntimeError('Invalid model response')
    calls = message.get('tool_calls') or []
    if not isinstance(calls, list):
        raise RuntimeError('Invalid model tool response')
    if not calls:
        content = message.get('content')
        if not isinstance(content, str):
            raise RuntimeError('Model did not return a response')
        return content[:6000]
    if len(calls) > MAX_CALLS:
        raise ValueError('Assistant requested too many tool calls')
    replies = []
    for call in calls:
        fn = call.get('function') or {}
        if call.get('type') != 'function' or fn.get('name') != 'queue_esn_check':
            replies.append('Rejected an unsupported action; only approved read-only tasks are permitted.')
            continue
        try:
            args = json.loads(fn.get('arguments') or '{}')
            if not isinstance(args, dict) or not set(args).issubset({'kind', 'target'}):
                raise ValueError('Unexpected task parameters')
            kind = args.get('kind')
            options = {'target': args['target']} if kind == 'browser_scan' and 'target' in args else {}
            if 'target' in args and kind != 'browser_scan':
                raise ValueError('Unexpected browser target')
            job_id = enqueue(kind, options)
            replies.append(f'Queued **{kind}** (job ID `{job_id}`). Check the Task Center for real results; this task is not finished yet.')
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            replies.append('Rejected an invalid task request (' + type(exc).__name__ + ').')
    return '\n'.join(replies)


def _authorized(handler):
    token = connections.token_from_cookie(handler.headers.get('Cookie', ''))
    return handler.authorized() or connections.session_valid(token)


def _csrf_ok(handler):
    if handler.authorized():
        return True
    token = connections.token_from_cookie(handler.headers.get('Cookie', ''))
    return connections.session_valid(token) and handler.headers.get('Origin', '') == connections.PUBLIC_ORIGIN and hmac.compare_digest(handler.headers.get('X-ESN-CSRF', ''), connections.csrf_token(token))


def handle(handler):
    path = urlsplit(handler.path).path
    if path not in ('/assistant', '/api/assistant/chat'):
        return False
    if not _authorized(handler):
        handler.send_json(401, {'error': 'Sign in to Connections first'}); return True
    if path == '/assistant' and handler.command == 'GET':
        handler.send_html((Path(__file__).with_name('web') / 'assistant.html').read_bytes()); return True
    if path == '/api/assistant/chat' and handler.command == 'POST':
        if not _csrf_ok(handler):
            handler.send_json(403, {'error': 'Request rejected'}); return True
        try:
            from jarvis import chat
            body = connections.read_json(handler)
            reply = chat(sanitize_message(body.get('message')))
        except (ValueError, TypeError) as exc:
            handler.send_json(400, {'error': str(exc)[:150]}); return True
        except (RuntimeError, KeyError, IndexError, ConnectionError):
            handler.send_json(503, {'error': 'AI provider is not configured or temporarily unavailable'}); return True
        handler.send_json(200, {'reply': reply}); return True
    handler.send_json(404, {'error': 'Not found'}); return True
