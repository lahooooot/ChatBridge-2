"""Local OpenAI-compatible facade; provider turns never execute desktop tools."""
from __future__ import annotations
import json
import logging
import queue
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .toolparse import extract_requests, strip_tool_blocks
from .provider_models import default_models, platform_for_model

log = logging.getLogger(__name__)
DEFAULT_MODELS = default_models()
MODELS = [entry['id'] for entry in DEFAULT_MODELS]


def flatten_messages(messages, tools=None):
    parts = []
    for message in messages:
        role = str(message.get('role', 'user'))
        content = message.get('content', '')
        if isinstance(content, list):
            content = '\n'.join(str(p.get('text', '')) for p in content if p.get('type') == 'text')
        parts.append(f'[{role}]\n{content or ""}')
        if message.get('tool_calls'):
            for call in message['tool_calls']:
                function = call.get('function', {})
                parts.append('```json\n' + json.dumps({
                    'tool': function.get('name'),
                    'args': json.loads(function.get('arguments', '{}'))}, ensure_ascii=False) + '\n```')
    if tools:
        parts.append('I can do things for you in your working folder. If you need an action, just tell me what to do and I will handle it. I can read and write files, list folders, search, run commands, inspect Git and fetch a public web page. Available actions:\n' + json.dumps(tools, ensure_ascii=False))
    return '\n\n'.join(parts)


class ProviderServer:
    def __init__(self, bridge, key, port=8788, timeout=600, models=None, ensure_browser=None,
                 connect_wait=30):
        self.bridge, self.key = bridge, key
        self.port, self.timeout = int(port), int(timeout)
        self.server = None
        self.waiters = {}
        self.lock = threading.Lock()
        self.models = self._normalize_models(models)
        # Optional Callable(platform) that opens the internal browser, so a
        # request can still work when the user enabled the provider but never
        # opened the browser by hand.
        self.ensure_browser = ensure_browser
        # How long a request waits for the freshly opened browser to connect.
        self.connect_wait = float(connect_wait)
        # Small, honest diagnostics for the settings panel: the user should be
        # able to see why a request stopped instead of guessing.
        self.served = 0
        self.last_error = ''
        self.last_request = None

    def _normalize_models(self, models):
        # Return the exposed models as id/name/platform entries.
        entries = []
        for row in models or DEFAULT_MODELS:
            if isinstance(row, str):
                row = {'id': row}
            if not isinstance(row, dict):
                continue
            model_id = str(row.get('id') or '').strip()
            if not model_id:
                continue
            platform = str(row.get('platform') or '').strip() or platform_for_model(model_id)
            name = str(row.get('name') or '').strip() or platform
            entries.append({'id': model_id, 'name': name, 'platform': platform})
        return entries

    def platform_for(self, model_id):
        # Return the browser platform id behind a provider model id.
        for entry in self.models:
            if entry['id'] == model_id:
                return entry['platform']
        return platform_for_model(model_id)

    def resolve_model(self, raw):
        """Return the exposed model id for a client-supplied model name.

        Clients are inconsistent: some send ``web-chatgpt`` while others send
        the provider-qualified ``chatbridge/web-chatgpt``. Accept both (and any
        letter case) so a correct key never fails with an opaque
        ``Unknown web model`` just because of a name prefix.
        """
        text = str(raw or '').strip()
        ids = [entry['id'] for entry in self.models]
        if text in ids:
            return text
        if '/' in text:
            tail = text.rsplit('/', 1)[-1].strip()
            if tail in ids:
                return tail
        lowered = text.lower()
        for model_id in ids:
            if model_id.lower() == lowered:
                return model_id
        return ''

    def status(self):
        """Return a small snapshot the settings panel can display live."""
        return {'running': bool(self.server),
                'browser_connected': bool(self.bridge.connected),
                'served': self.served,
                'last_error': self.last_error,
                'last_request': dict(self.last_request) if self.last_request else None,
                'models': [entry['id'] for entry in self.models]}

    def _record(self, model, ok, error=''):
        with self.lock:
            if ok:
                self.served += 1
            if error:
                self.last_error = str(error)
            self.last_request = {'model': str(model or ''), 'ok': bool(ok),
                                 'error': str(error or ''),
                                 'ts': time.strftime('%Y-%m-%d %H:%M:%S')}

    def _open_browser(self, platform):
        # Best effort: the settings panel and the normal send path can open the
        # browser, so the provider should not require the user to do it first.
        if not self.ensure_browser:
            return
        try:
            self.ensure_browser(platform)
        except Exception as exc:
            log.warning('Could not open the internal browser for the provider: %s', exc)

    def _wait_connected(self, seconds=None):
        timeout = self.connect_wait if seconds is None else float(seconds)
        deadline = time.monotonic() + timeout
        while not self.bridge.connected and time.monotonic() < deadline:
            time.sleep(0.15)
        return bool(self.bridge.connected)

    def _connect(self, platform):
        """Make sure a driver is attached, opening the browser if we can.

        Returns True when the bridge is connected. Without an ``ensure_browser``
        hook nothing can attach a driver, so fail fast instead of blocking the
        HTTP thread for the whole connect window.
        """
        if self.bridge.connected:
            return True
        if not self.ensure_browser:
            return False
        self._open_browser(platform)
        return self._wait_connected()

    def on_event(self, event):
        rid = event.get('request_id', '')
        if not rid.startswith('prov-'):
            return
        with self.lock:
            target = self.waiters.get(rid)
        if target:
            target.put(dict(event))

    def start(self):
        owner = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, fmt, *args):
                return

            def respond(self, status, payload):
                data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def authenticated(self):
                token = self.headers.get('Authorization', '')
                if not secrets.compare_digest(token, 'Bearer ' + owner.key):
                    self.respond(401, {'error': {'message': 'Invalid provider API key', 'type': 'authentication_error'}})
                    return False
                return True

            def do_GET(self):
                if self.path == '/health':
                    self.respond(200, {'ok': True, 'running': bool(owner.server),
                                       'browser_connected': bool(owner.bridge.connected),
                                       'models': [entry['id'] for entry in owner.models]})
                elif self.authenticated():
                    route = self.path.rstrip('/')
                    if route.startswith('/v1/models/'):
                        model_id = route[len('/v1/models/'):]
                        entry = next((item for item in owner.models if item['id'] == model_id), None)
                        if entry:
                            self.respond(200, {'id': entry['id'], 'object': 'model', 'created': 0,
                                                'owned_by': 'chatbridge', 'name': entry['name']})
                        else:
                            self.respond(404, {'error': {'message': 'Unknown model'}})
                    elif route == '/v1/models':
                        self.respond(200, {'object': 'list', 'data': [
                            {'id': entry['id'], 'object': 'model', 'created': 0,
                             'owned_by': 'chatbridge', 'name': entry['name']} for entry in owner.models]})
                    else:
                        self.respond(404, {'error': {'message': 'Not found'}})

            def do_POST(self):
                if not self.authenticated():
                    return
                if self.path.rstrip('/') != '/v1/chat/completions':
                    self.respond(404, {'error': {'message': 'Not found'}})
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if length < 1 or length > 2*1024*1024:
                        raise ValueError('Request size must be between 1 byte and 2 MB')
                    body = json.loads(self.rfile.read(length))
                    requested = str(body.get('model') or (owner.models[0]['id'] if owner.models else 'web-chatgpt'))
                    model = owner.resolve_model(requested)
                    if not model:
                        raise ValueError('Unknown web model "' + requested + '". Available: '
                                         + ', '.join(entry['id'] for entry in owner.models))
                    messages = body.get('messages')
                    if not isinstance(messages, list) or not messages or any(not isinstance(x, dict) for x in messages):
                        raise ValueError('messages must be a nonempty array of objects')
                    prompt = flatten_messages(messages, body.get('tools'))
                except (ValueError, TypeError, KeyError) as exc:
                    owner._record('', False, str(exc))
                    self.respond(400, {'error': {'message': str(exc), 'type': 'invalid_request_error'}})
                    return
                platform = owner.platform_for(model)
                if not owner._connect(platform):
                    error = ('The internal browser is not connected. Open it, sign in to the '
                             'web model, then try again.')
                    owner._record(model, False, error)
                    self.respond(503, {'error': {'message': error, 'type': 'browser_unavailable'}})
                    return
                rid = 'prov-' + uuid.uuid4().hex
                completion_id = 'chatcmpl-' + uuid.uuid4().hex
                events = queue.Queue()
                with owner.lock:
                    owner.waiters[rid] = events
                owner.bridge.send({'type': 'user_message', 'text': prompt, 'platform': platform,
                                   'request_id': rid, 'fresh': True})
                streaming = bool(body.get('stream'))
                sent = ''
                started = time.monotonic()
                try:
                    if streaming:
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                        self.send_header('Cache-Control', 'no-cache')
                        self.send_header('Connection', 'close')
                        self.end_headers()
                        self.sse(self.chunk(completion_id, model, {'role': 'assistant'}, None))
                    while time.monotonic() - started < owner.timeout:
                        try:
                            event = events.get(timeout=min(5, max(0.01, owner.timeout-(time.monotonic()-started))))
                        except queue.Empty:
                            if streaming:
                                self.wfile.write(b': heartbeat\n\n')
                                self.wfile.flush()
                            continue
                        kind = event['type']
                        if kind == 'assistant_stream' and streaming:
                            text = strip_tool_blocks(event.get('text', ''))
                            if text.startswith(sent) and len(text) > len(sent):
                                self.sse(self.chunk(completion_id, model, {'content': text[len(sent):]}, None))
                                sent = text
                        elif kind == 'assistant_response':
                            raw = event.get('text', '')
                            text = strip_tool_blocks(raw)
                            requests = event.get('requests')
                            calls = [call for call in (requests if requests is not None
                                                      else extract_requests(raw))
                                     if call['tool'] != '__parse_error__']
                            native = [{'id': c['id'], 'type': 'function', 'function': {
                                'name': c['tool'], 'arguments': json.dumps(c['args'], ensure_ascii=False)}} for c in calls]
                            finish = 'tool_calls' if native else 'stop'
                            if streaming:
                                delta = {}
                                if text.startswith(sent) and text[len(sent):]:
                                    delta['content'] = text[len(sent):]
                                if native:
                                    delta['tool_calls'] = [{'index': i, **c} for i, c in enumerate(native)]
                                if delta:
                                    self.sse(self.chunk(completion_id, model, delta, None))
                                self.sse(self.chunk(completion_id, model, {}, finish))
                                self.wfile.write(b'data: [DONE]\n\n')
                                self.wfile.flush()
                                self.close_connection = True
                            else:
                                message = {'role': 'assistant', 'content': text or None}
                                if native:
                                    message['tool_calls'] = native
                                self.respond(200, {'id': completion_id, 'object': 'chat.completion',
                                    'created': int(time.time()), 'model': model,
                                    'choices': [{'index': 0, 'message': message, 'finish_reason': finish}],
                                    'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0},
                                    'chatbridge': {'usage_is_unavailable': True}})
                            owner._record(model, True)
                            return
                        elif kind in ('assistant_capture_failed', 'prompt_error'):
                            raise RuntimeError(event.get('reason', 'Browser response unavailable'))
                    raise TimeoutError('Provider browser response timed out')
                except (BrokenPipeError, ConnectionResetError):
                    owner._record(model, False, 'client-disconnected')
                    owner.bridge.send({'type': 'stop_generation', 'request_id': rid, 'platform': platform})
                except Exception as exc:
                    owner._record(model, False, str(exc))
                    if streaming:
                        try:
                            self.sse({'error': {'message': str(exc), 'type': 'browser_error'}})
                            self.wfile.write(b'data: [DONE]\n\n')
                            self.wfile.flush()
                        except OSError:
                            pass
                        self.close_connection = True
                    else:
                        self.respond(504 if isinstance(exc, TimeoutError) else 502,
                                     {'error': {'message': str(exc), 'type': 'browser_error'}})
                    owner.bridge.send({'type': 'stop_generation', 'request_id': rid, 'platform': platform})
                finally:
                    with owner.lock:
                        owner.waiters.pop(rid, None)

            def sse(self, payload):
                self.wfile.write(('data: ' + json.dumps(payload, ensure_ascii=False) + '\n\n').encode('utf-8'))
                self.wfile.flush()

            @staticmethod
            def chunk(cid, model, delta, finish):
                return {'id': cid, 'object': 'chat.completion.chunk', 'created': int(time.time()),
                        'model': model, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
        self.server = ThreadingHTTPServer(('127.0.0.1', self.port), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True, name='provider-http').start()
        return self

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
