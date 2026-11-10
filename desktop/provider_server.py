"""Local OpenAI-compatible facade; provider turns never execute desktop tools."""
from __future__ import annotations
import json
import queue
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .toolparse import parse_tool_calls, strip_tool_blocks

MODELS = ['web-chatgpt', 'web-claude', 'web-deepseek', 'web-zai', 'web-gemini']


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
                parts.append('```chatbridge-tool-call\n' + json.dumps({
                    'id': call.get('id'), 'tool': function.get('name'),
                    'args': json.loads(function.get('arguments', '{}'))}, ensure_ascii=False) + '\n```')
    if tools:
        parts.append('I have tools available in my client. To request one, please write a compact JSON object in a chatbridge-tool-call code fence with tool and args fields. I will execute it in my client, not in this browser. Available tool schemas:\n' + json.dumps(tools, ensure_ascii=False))
    return '\n\n'.join(parts)


class ProviderServer:
    def __init__(self, bridge, key, port=8788, timeout=600):
        self.bridge, self.key = bridge, key
        self.port, self.timeout = int(port), int(timeout)
        self.server = None
        self.waiters = {}
        self.lock = threading.Lock()

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
                    self.respond(200, {'ok': True, 'browser_connected': owner.bridge.connected})
                elif self.authenticated():
                    if self.path.rstrip('/') == '/v1/models':
                        self.respond(200, {'object': 'list', 'data': [
                            {'id': model, 'object': 'model', 'created': 0, 'owned_by': 'chatbridge'} for model in MODELS]})
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
                    model = body.get('model', 'web-chatgpt')
                    if model not in MODELS:
                        raise ValueError('Unknown web model')
                    messages = body.get('messages')
                    if not isinstance(messages, list) or not messages or any(not isinstance(x, dict) for x in messages):
                        raise ValueError('messages must be a nonempty array of objects')
                    prompt = flatten_messages(messages, body.get('tools'))
                except (ValueError, TypeError, KeyError) as exc:
                    self.respond(400, {'error': {'message': str(exc), 'type': 'invalid_request_error'}})
                    return
                if not owner.bridge.connected:
                    self.respond(503, {'error': {'message': 'Open the internal browser and sign in first.', 'type': 'browser_unavailable'}})
                    return
                rid = 'prov-' + uuid.uuid4().hex
                completion_id = 'chatcmpl-' + uuid.uuid4().hex
                events = queue.Queue()
                with owner.lock:
                    owner.waiters[rid] = events
                owner.bridge.send({'type': 'user_message', 'text': prompt, 'platform': model[4:],
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
                            calls = [call for call in parse_tool_calls(raw) if call['tool'] != '__parse_error__']
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
                            return
                        elif kind in ('assistant_capture_failed', 'prompt_error'):
                            raise RuntimeError(event.get('reason', 'Browser response unavailable'))
                    raise TimeoutError('Provider browser response timed out')
                except (BrokenPipeError, ConnectionResetError):
                    owner.bridge.send({'type': 'stop_generation', 'request_id': rid, 'platform': model[4:]})
                except Exception as exc:
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
                    owner.bridge.send({'type': 'stop_generation', 'request_id': rid, 'platform': model[4:]})
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
