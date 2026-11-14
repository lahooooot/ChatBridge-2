"""ChatBridge 2.60.0 entry point and pywebview API."""
from __future__ import annotations
import base64
import functools
import importlib
import json
import logging
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = 'desktop'

from . import hints
from .bridge import Bridge, UISink
from .config import ConfigStore, default_data_dir
from .safety import Workspace
from .fstree import FileTree
from .terminal import TerminalManager
from .gittools import GitTools
from .project import ProjectRegistry
from .chatfolder import create_chat_folder
from .audit import AuditLog
from .internal_browser import InternalBrowser, PLATFORM_HOME, profile_path
from .provider_server import ProviderServer
from .toolparse import parse_tool_calls, strip_tool_blocks
from .tools._extended import HANDLERS as EXTENDED_TOOLS

APP_VERSION = '2.60.0'
WORKSPACE_TOOLS = (
    'read_file', 'write_file', 'list_dir', 'search_files', 'run_command',
    'edit_file', 'stat_file', 'append_file', 'make_dir', 'delete_file',
    'rename_file', 'move_file', 'copy_file', 'glob', 'grep', 'diff_preview',
    'read_multiple_files', 'tail_file', 'outline', 'find_symbol',
)
TOOLS = WORKSPACE_TOOLS + tuple(EXTENDED_TOOLS)
APPROVAL_TOOLS = frozenset({
    'write_file', 'run_command', 'edit_file', 'append_file', 'make_dir',
    'delete_file', 'rename_file', 'move_file', 'copy_file',
    'git_stage', 'git_unstage', 'git_commit', 'git_checkout',
    'snapshot', 'rollback', 'run_tests', 'http_fetch', 'process_control',
})
MAX_FILE = 15 * 1024 * 1024
log = logging.getLogger(__name__)


def guarded(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            log.exception('API %s failed', fn.__name__)
            return {'ok': False, 'error': str(exc)}
    return wrapped


def data_url(name, content, mime=None):
    mime = mime or mimetypes.guess_type(name)[0] or ('text/plain' if name.endswith(('.txt', '.text', '.log')) else 'application/octet-stream')
    return 'data:' + mime + ';base64,' + base64.b64encode(content).decode('ascii')


def decode_data(value):
    if not isinstance(value, str) or not value.startswith('data:') or ';base64,' not in value:
        raise ValueError('A base64 data URL is required')
    if len(value) > MAX_FILE * 1.4 + 1024:
        raise ValueError('Files are limited to 15 MB')
    content = base64.b64decode(value.split(',', 1)[1], validate=True)
    if len(content) > MAX_FILE:
        raise ValueError('Files are limited to 15 MB')
    return content


class Api:
    def __init__(self, base=None):
        self.base = Path(base or default_data_dir())
        self.base.mkdir(parents=True, exist_ok=True)
        self.config = ConfigStore(self.base)
        self.sink = UISink()
        # Must remain private. pywebview walks public js_api attributes when
        # building its native accessibility bridge; exposing a Window object
        # here creates AccessibilityObject.Bounds.Empty recursion on WinForms.
        self._window = None
        self.registry = ProjectRegistry(self.base)
        self.audit = AuditLog(self.base / 'audit.db')
        self.terminal = TerminalManager(self.sink)
        self.project = None
        self.requests = {}
        self.chat_urls = {}
        self.approvals = {}
        self.seen_tools = set()
        self.lock = threading.RLock()
        log_dir = self.base / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._event_log_path = log_dir / "chatbridge-events.log"
        self._event_log_lock = threading.Lock()
        self.provider = None
        self.bridge = Bridge(self.config.get().get('ws_port', 8787), self.sink, self._event)
        homes = {m['id']: m['home'] for m in self.config.get().get('custom_models', [])}
        self._browser = InternalBrowser(self.bridge, self.sink, homes)
        # Standalone, shareable per-host selector file (platform_hints.json).
        self._browser.hints_provider = self._host_hints
        self._browser.hint_recorder = self._record_hint_failure
        state = self.config.load_state()
        root = state.get('project_path') if isinstance(state, dict) else None
        if root and Path(root).is_dir():
            self.project = self.registry.attach(root)
        for chat in state.get('chats', []):
            if isinstance(chat, dict) and chat.get('id') and chat.get('url'):
                self.chat_urls[chat['id']] = chat['url']
        self.last_platforms = state.get('_last_platforms', {
            chat['id']: chat.get('platform') for chat in state.get('chats', []) if isinstance(chat, dict) and chat.get('id')})

    def start(self):
        self.bridge.start()
        if self.config.get().get('provider_enabled'):
            self._start_provider()

    def shutdown(self):
        """Release every resident resource before pywebview exits."""
        try:
            self._browser.shutdown()
        finally:
            self.bridge.stop()
            if self.provider:
                self.provider.stop()
                self.provider = None
            # Closing the parent window does not always stop pywebview when a
            # docked child WebView2 window still exists. Explicitly stop the
            # GUI loop so the frozen EXE leaves no ChatBridge process behind.
            try:
                import webview
                webview.stop()
            except Exception:
                log.exception('Could not stop pywebview cleanly')
            # A frozen WebView2 build can keep the interpreter and the
            # PyInstaller child alive after the GUI loop stops because native
            # Edge/WebView2 subprocesses still hold handles. After a short
            # grace period force the process out so no ChatBridge process is
            # left behind. Restricted to frozen EXEs so source/test runs are
            # unaffected.
            if getattr(sys, 'frozen', False):
                def _force_exit():
                    # Give the bridge time to wait_closed() and release port
                    # 8787 before the process is forced out.
                    time.sleep(5.0)
                    os._exit(0)
                threading.Thread(target=_force_exit, daemon=True, name='force-exit').start()

    def _spawn(self, fn, kind='task_result', **context):
        ident = uuid.uuid4().hex
        def run():
            try:
                result = fn()
                event = {'type': kind, 'id': ident, 'ok': True, 'result': result, **context}
                if isinstance(result, dict):
                    event.update(result)
            except Exception as exc:
                log.exception('Background operation failed')
                event = {'type': kind, 'id': ident, 'ok': False, 'error': str(exc), **context}
            self.sink(event)
        threading.Thread(target=run, daemon=True, name=kind).start()
        return {'ok': True, 'id': ident}

    def _root(self):
        if not self.project:
            raise ValueError('Attach a project or create a chat folder first.')
        return self.project['path']

    def _log_ui_event(self, event):
        try:
            record = dict(event)
            record.setdefault("ts", time.strftime("%Y-%m-%d %H:%M:%S"))
            with self._event_log_lock:
                with self._event_log_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False, default=str)[:20000] + "\n")
        except Exception:
            log.debug("UI event logging failed", exc_info=True)

    def _event(self, event):
        event = dict(event)
        self._log_ui_event(event)
        if self.provider:
            self.provider.on_event(event)
        if event.get('type') == 'approval_response':
            # Remote DOM/JavaScript is not an authorization boundary. A page can
            # synthesize button clicks and replace the agent's return values.
            if not event.get('approved', False):
                self.approval_response(event.get('id'), False)
            else:
                log.warning('Ignored untrusted remote approval id=%s', event.get('id'))
            return
        rid = event.get('request_id', '')
        owner = self.requests.get(rid, {})
        if owner:
            event['chat_id'] = owner['chat_id']
            if event.get('page_url'):
                self.chat_urls[owner['chat_id']] = event['page_url']
            owner['heartbeat'] = time.monotonic()
        if owner.get('stopped') and event['type'] in ('assistant_stream', 'assistant_response', 'assistant_waiting', 'tool_call'):
            return
        if event['type'] == 'tool_call' and not rid.startswith('prov-'):
            key = (rid, event['id'])
            with self.lock:
                if key in self.seen_tools:
                    return
                self.seen_tools.add(key)
            threading.Thread(target=self._execute_tool, args=(event,), daemon=True, name='tool-execute').start()
            return
        if event['type'] in ('assistant_stream', 'assistant_response'):
            raw = event.get('text', '')
            event['text'] = strip_tool_blocks(raw)
            calls = event.pop('parsed_calls', None)
            if calls is None:
                calls = parse_tool_calls(raw) if event['type'] == 'assistant_response' else []
            event['operations'] = [self._operation(c) for c in calls if c['tool'] != '__parse_error__']
        if event['type'] == 'file_data':
            event['type'] = 'file_ready'
        self.sink(event)

    @staticmethod
    def _operation(call):
        tool, args = call.get('tool'), call.get('args', {})
        verbs = {'read_file': 'read', 'write_file': 'edit' if 'search' in args else 'write',
                 'list_dir': 'list', 'search_files': 'grep', 'run_command': 'run',
                 'edit_file': 'edit', 'stat_file': 'stat', 'append_file': 'append',
                 'make_dir': 'mkdir', 'delete_file': 'delete', 'rename_file': 'move',
                 'move_file': 'move', 'copy_file': 'copy', 'glob': 'glob',
                 'grep': 'grep', 'diff_preview': 'diff', 'read_multiple_files': 'read',
                 'tail_file': 'tail', 'outline': 'outline', 'find_symbol': 'find',
                 'git_status': 'git', 'git_diff': 'git', 'git_log': 'git',
                 'git_show': 'git', 'git_blame': 'git', 'git_stage': 'git',
                 'git_unstage': 'git', 'git_commit': 'git', 'git_branch': 'git',
                 'git_checkout': 'git', 'snapshot': 'snapshot', 'rollback': 'rollback',
                 'process_control': 'process', 'run_tests': 'test', 'http_fetch': 'fetch'}
        return {'id': call['id'], 'tool': tool, 'verb': verbs.get(tool, 'tool'),
                'target': str(args.get('path', args.get('cmd', args.get('query', tool)))), 'args': args,
                'status': 'pending'}

    def _approve(self, ident, tool, args, request_id=None):
        if self.config.get().get('full_access', True):
            return True
        ready = threading.Event()
        box = {'event': ready, 'approved': False}
        with self.lock:
            self.approvals[ident] = box
        payload = {'type': 'approval_required', 'id': ident, 'tool': tool,
                   'summary': str(args.get('path', args.get('cmd', tool))),
                   'detail': json.dumps(args, ensure_ascii=False)[:20000],
                   'timeout': self.config.get().get('approval_timeout', 120), 'request_id': request_id}
        if request_id in self.requests:
            payload['chat_id'] = self.requests[request_id]['chat_id']
        self.sink(payload)
        self.bridge.send(payload)
        deadline = time.monotonic() + int(payload['timeout'])
        while time.monotonic() < deadline:
            if ready.wait(0.25):
                break
            if self.requests.get(request_id, {}).get('stopped'):
                break
        with self.lock:
            self.approvals.pop(ident, None)
        self.sink({'type': 'approval_closed', 'id': ident, 'approved': box['approved']})
        self.bridge.send({'type': 'approval_closed', 'id': ident, 'approved': box['approved']})
        return box['approved']

    def _execute_tool(self, call):
        rid, ident, tool, args = call['request_id'], call['id'], call['tool'], call.get('args', {})
        owner = self.requests.get(rid, {})
        if owner.get('stopped'):
            return
        result, error, ok = None, None, False
        operation = self._operation(call)
        try:
            if tool == '__parse_error__':
                raise ValueError('The tool request could not be parsed (' + str(args.get('reason')) + '). Please resend one compact standard chatbridge-tool-call JSON block with tool and args. Available tools: ' + ', '.join(TOOLS))
            if tool not in TOOLS:
                raise ValueError('Unknown tool. Available tools: ' + ', '.join(TOOLS))
            root = owner.get('workspace')
            if not root:
                raise ValueError('No workspace is attached; ask me to attach a project first.')
            workspace = Workspace(root)
            if tool in APPROVAL_TOOLS and not self._approve(ident, tool, args, rid):
                raise PermissionError('Approval denied or timed out')
            if self.requests.get(rid, {}).get('stopped'):
                return
            self.sink({'type': 'tool_started', 'request_id': rid, 'chat_id': owner.get('chat_id'), **operation})
            if tool == 'run_command':
                cwd = str(workspace.resolve(args.get('cwd', '.')))
                terminal_id = self.terminal.run(args['cmd'], cwd, int(args.get('timeout', 300)))
                operation['terminal_id'] = terminal_id
                self.sink({'type': 'tool_terminal', 'id': ident, 'terminal_id': terminal_id,
                           'request_id': rid, 'chat_id': owner.get('chat_id')})
                while True:
                    value = self.terminal.result(terminal_id)
                    if value and not value.get('running', True):
                        result = value
                        break
                    if owner.get('stopped'):
                        self.terminal.kill(terminal_id)
                        return
                    time.sleep(0.1)
            elif tool in EXTENDED_TOOLS:
                result = EXTENDED_TOOLS[tool](workspace, args, self)
            else:
                result = getattr(workspace, tool)(**args)
            ok = True
        except Exception as exc:
            error = str(exc)
        try:
            self.audit.record(tool, args, ok, result=result, error=error)
        except Exception:
            log.exception('Audit recording failed')
        operation.update(status='done' if ok else 'error', ok=ok, result=result, error=error)
        self.sink({'type': 'tool_finished', 'request_id': rid, 'chat_id': owner.get('chat_id'), **operation})
        if ok and tool in {'write_file', 'edit_file', 'append_file', 'make_dir', 'delete_file',
                           'rename_file', 'move_file', 'copy_file'}:
            self.sink({'type': 'fs_changed', 'path': args.get('path') or args.get('new_path'), 'request_id': rid})
        if owner.get('stopped'):
            return
        packet = {'type': 'tool_result', 'id': ident, 'ok': ok, 'result': result, 'error': error,
                  'platform': call['platform'], 'request_id': rid, 'conv_url': call.get('page_url')}
        serialized = json.dumps(result, ensure_ascii=False, default=str) if result is not None else ''
        if len(serialized) > 12000 and owner.get('workspace'):
            directory = Workspace(owner['workspace']).resolve('.chatbridge/results')
            directory.mkdir(parents=True, exist_ok=True)
            filename = re.sub(r'[^a-zA-Z0-9_-]', '_', ident)[:100] + '.txt'
            path = directory / filename
            path.write_text(serialized, encoding='utf-8')
            packet['result'] = {'preview': serialized[:10000], 'truncated': True,
                                'full_result_path': str(path.relative_to(owner['workspace']))}
            content = serialized.encode('utf-8')
            if len(content) <= MAX_FILE:
                packet['attachment'] = {'name': filename, 'mime': 'text/plain', 'data_url': data_url(filename, content)}
        self.bridge.send(packet)

    def _host_hints(self, host):
        try:
            return hints.for_host(self.config.base, host)
        except Exception:
            log.debug('Hint lookup failed for %s', host)
            return {}

    def _record_hint_failure(self, host, reason, observed):
        try:
            if hints.record_observation(self.config.base, host, reason, observed):
                self.sink({'type': 'browser_log',
                           'text': 'Saved selector observation for %s (%s). Review it in Settings > Models.' % (host, reason)})
        except Exception:
            log.debug('Hint observation failed for %s', host)

    @guarded
    def hints_get(self, host=''):
        return {'ok': True, **hints.suggest(self.config.base, host)}

    @guarded
    def hints_set(self, host, selectors):
        result = hints.set_host(self.config.base, host, selectors or {})
        self._browser.reinject()
        return {'ok': True, **result}

    @guarded
    def hints_pick(self, host, mode):
        if mode not in ('editor', 'send', 'body'):
            raise ValueError('Unknown picker mode')
        result = self._browser.pick_now(mode)
        if not result.get('ok'):
            return {'ok': False, 'error': result.get('error', 'picker-unavailable')}
        return {'ok': True, 'mode': mode, 'host': host, 'waiting': True}

    @guarded
    def browser_overlay(self, active):
        """Hide the docked browser while an HTML modal is open."""
        return self._browser.set_overlay(bool(active))

    @guarded
    def hints_pick_cancel(self):
        return {'ok': True, 'result': self._browser.call('pickCancel', timeout=5)}

    @guarded
    def hints_detect(self, host=''):
        """Open the site in the internal browser (user signs in) and probe it."""
        host = (host or '').lower()
        platform, home = None, None
        for model in self.config.get().get('custom_models', []):
            if hints.host_of(model.get('home')) == host:
                platform, home = model['id'], model['home']
                break
        if not home:
            return {'ok': False, 'error': 'unknown-host', 'host': host}
        if not self._browser.window:
            self._browser.open(platform)
            if not self._browser._loaded.wait(30):
                return {'ok': False, 'error': 'page-not-ready', 'host': host}
        else:
            nav = self._browser.navigate_and_wait(home, host, timeout=30)
            if not nav.get('ok'):
                return {'ok': False, 'error': nav.get('error', 'nav-failed'),
                        'host': host, 'page_url': nav.get('url', '')}
        return {'ok': True, 'detection': self._browser.detect_now(host)}

    @guarded
    def bootstrap(self):
        config = self.config.get()
        platforms = [{'id': key, 'name': {'chatgpt': 'ChatGPT', 'claude': 'Claude', 'zai': 'z.ai',
                        'deepseek': 'DeepSeek', 'gemini': 'Gemini'}[key], 'home': home}
                     for key, home in PLATFORM_HOME.items()]
        platforms.extend(config.get('custom_models', []))
        return {'ok': True, 'version': APP_VERSION, 'config': config, 'state': self.config.load_state(),
                'platforms': platforms, 'project': self.project,
                'provider': {'enabled': bool(self.provider), 'port': config.get('provider_port', 8788),
                             'key': config.get('provider_key')},
                'status': {'connected': self.bridge.connected}}

    @guarded
    def drain_events(self):
        return {'ok': True, 'events': self.sink.drain()}

    @guarded
    def state_save(self, state):
        state = dict(state)
        if 'project_path' in state:
            root = state.get('project_path')
            if root:
                if not Path(root).is_dir():
                    raise ValueError('The active chat workspace no longer exists.')
                if not self.project or self.project['path'] != str(Path(root).resolve()):
                    self.project = self.registry.attach(root)
            else:
                self.project = None
        for chat in state.get('chats', []):
            if isinstance(chat, dict) and chat.get('id'):
                if chat.get('url'):
                    self.chat_urls[chat['id']] = chat['url']
                else:
                    self.chat_urls.pop(chat['id'], None)
        state['_last_platforms'] = self.last_platforms
        self.config.save_state(state)
        return {'ok': True}

    @guarded
    def config_set(self, patch):
        old = self.config.get()
        config = self.config.update(patch)
        self._browser.homes.update({m['id']: m['home'] for m in config.get('custom_models', [])})
        if config.get('ws_port') != old.get('ws_port'):
            self.sink({'type': 'notice', 'text': 'Restart ChatBridge to apply the WebSocket port change.'})
        return {'ok': True, 'config': config}

    @guarded
    def send_message(self, text, platform, chat_id, attachment=None):
        if not text.strip() and not attachment:
            raise ValueError('Write a message or attach a file.')
        if platform not in self._browser.homes:
            raise ValueError('Unknown platform')
        if attachment:
            decode_data(attachment['data_url'])
        rid = uuid.uuid4().hex
        root = self.project['path'] if self.project else None
        self.requests[rid] = {'chat_id': chat_id, 'workspace': root, 'heartbeat': time.monotonic(), 'stopped': False}
        previous_platform = self.last_platforms.get(chat_id)
        self.last_platforms[chat_id] = platform
        context = ''
        if previous_platform and previous_platform != platform:
            saved_chat = next((c for c in self.config.load_state().get('chats', []) if c.get('id') == chat_id), {})
            transcript = '\n\n'.join(str(m.get('role', 'user')) + ': ' + strip_tool_blocks(str(m.get('text', '')))[:2500]
                                      for m in saved_chat.get('messages', [])[-8:])
            if transcript:
                context = 'I changed my chat service. Here is the recent context of my conversation:\n' + transcript[-12000:] + '\n\nMy next message:\n'
        conv_url = self.chat_urls.get(chat_id)
        from urllib.parse import urlparse
        if conv_url and urlparse(conv_url).netloc != urlparse(self._browser.homes[platform]).netloc:
            conv_url = None
        # Bounded routing memory; retain active turns and recent stopped turns.
        if len(self.requests) > 1000:
            oldest = next(iter(self.requests))
            self.requests.pop(oldest, None)
            self.seen_tools = {k for k in self.seen_tools if k[0] != oldest}
        def send():
            prompt = self.config.rules_preview(context + text, root) if root else context + text
            file = attachment
            if len(prompt) > 18000:
                if attachment:
                    raise ValueError('For a very long message, send the existing attachment separately first.')
                content = prompt.encode('utf-8')
                if len(content) > MAX_FILE:
                    raise ValueError('The message exceeds the 15 MB attachment limit.')
                file = {'name': 'message-' + rid[:8] + '.txt', 'mime': 'text/plain',
                        'data_url': data_url('message.txt', content)}
                prompt = 'I attached my full message as a text file. Please read it and respond to the instructions inside.'
            self._browser.open(platform)
            self.bridge.send({'type': 'user_message', 'text': prompt, 'platform': platform,
                              'request_id': rid, 'conv_url': conv_url, 'attachment': file})
            return {'request_id': rid}
        self._spawn(send, kind='message_queued', request_id=rid, chat_id=chat_id)
        return {'ok': True, 'request_id': rid}

    @guarded
    def stop_message(self, request_id, platform):
        if request_id in self.requests:
            self.requests[request_id]['stopped'] = True
        self.bridge.send({'type': 'stop_generation', 'request_id': request_id, 'platform': platform})
        self.sink({'type': 'generation_stopped', 'request_id': request_id})
        return {'ok': True}

    @guarded
    def new_web_chat(self, platform, resume=''):
        return self._web_request('new_chat', platform, resume=resume)

    def _web_request(self, kind, platform, **extra):
        rid = uuid.uuid4().hex
        self._browser.open(platform)
        self.bridge.send({'type': kind, 'platform': platform, 'request_id': rid, **extra})
        return {'ok': True, 'request_id': rid}

    @guarded
    def list_web_chats(self, platform):
        return self._web_request('list_chats', platform)

    @guarded
    def read_web_chat(self, platform, url, limit=40):
        return self._web_request('read_chat', platform, url=url, limit=limit)

    @guarded
    def load_older(self, platform, url):
        return self._web_request('load_older', platform, url=url)

    @guarded
    def ibrowser_open(self, platform='chatgpt'):
        self._browser.open(platform)
        return {'ok': True, 'status': {'connected': self.bridge.connected, 'browser_open': True,
                                        'page_url': self._browser.homes.get(platform, PLATFORM_HOME['chatgpt'])}}

    @guarded
    def ibrowser_close(self):
        self._browser.close()
        return {'ok': True}

    @guarded
    def ibrowser_fit(self, x, y, w, h, visible, cw, ch):
        self._browser.fit(x, y, w, h, bool(visible), cw, ch)
        return {'ok': True}

    @guarded
    def browser_nav(self, action, url=''):
        self._browser.navigate(action, url)
        return {'ok': True}

    @guarded
    def browser_reinject(self):
        self._browser.reinject()
        return {'ok': True}

    @guarded
    def browser_reset_profile(self):
        self.config.update({'reset_profile_next_start': True})
        self.sink({'type': 'notice', 'text': 'Profile reset scheduled for next start. All web sessions will be signed out.'})
        return {'ok': True, 'restart_required': True}

    @guarded
    def project_attach(self, path=''):
        if not path:
            def choose():
                import webview
                chosen = self._window.create_file_dialog(webview.FileDialog.FOLDER)
                if not chosen:
                    return {'ok': False, 'error': 'Folder selection cancelled'}
                self.project = self.registry.attach(chosen[0])
                return {'project': self.project}
            return self._spawn(choose, kind='project_attached')
        self.project = self.registry.attach(path)
        self.sink({'type': 'project_attached', 'ok': True, 'project': self.project})
        return {'ok': True, 'project': self.project}

    @guarded
    def chat_folder(self, name):
        project = create_chat_folder(name)
        self.project = self.registry.attach(project['path'])
        self.sink({'type': 'project_attached', 'ok': True, 'project': self.project})
        return {'ok': True, 'project': self.project}

    @guarded
    def fs_tree(self, path=''):
        return {'ok': True, **FileTree(self._root()).tree(path)}

    @guarded
    def fs_read(self, path):
        return {'ok': True, **FileTree(self._root()).read(path)}

    @guarded
    def fs_write(self, path, content):
        root = self._root()
        ident = uuid.uuid4().hex
        def write():
            if not self._approve(ident, 'write_file', {'path': path, 'content': content}):
                raise PermissionError('Approval denied or timed out')
            try:
                result = FileTree(root).write(path, content)
                self.audit.record('write_file', {'path': path, 'source': 'editor'}, True, result=result)
                self.sink({'type': 'fs_changed', 'path': path})
                return result
            except Exception as exc:
                self.audit.record('write_file', {'path': path, 'source': 'editor'}, False, error=str(exc))
                raise
        return self._spawn(write, kind='fs_saved', path=path)

    @guarded
    def reveal_path(self, path):
        target = Workspace(self._root()).resolve(path)
        def reveal():
            if os.name == 'nt':
                subprocess.Popen(['explorer', '/select,', str(target)])
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', '-R', str(target)])
            else:
                subprocess.Popen(['xdg-open', str(target if target.is_dir() else target.parent)])
            return {'ok': True}
        return self._spawn(reveal)

    @guarded
    def terminal_run(self, cmd, cwd='', timeout=300):
        root = self._root()
        cwd = str(Workspace(root).resolve(cwd or '.'))
        if not self.config.get().get('full_access', True):
            def approved_run():
                if not self._approve(uuid.uuid4().hex, 'run_command', {'cmd': cmd, 'cwd': cwd}):
                    raise PermissionError('Approval denied or timed out')
                return {'terminal_id': self.terminal.run(cmd, cwd, timeout)}
            return self._spawn(approved_run, kind='terminal_started')
        return {'ok': True, 'id': self.terminal.run(cmd, cwd, timeout)}

    @guarded
    def terminal_kill(self, id):
        return {'ok': self.terminal.kill(id)}

    @guarded
    def terminal_send(self, id, platform, chat_id):
        result = self.terminal.result(id)
        if not result:
            raise ValueError('Terminal session not found')
        return self.send_message('Here is the output of my local command:\n' + json.dumps(result, ensure_ascii=False), platform, chat_id)

    @guarded
    def git_status(self):
        return {'ok': True, **GitTools(self._root()).status()}

    @guarded
    def git_action(self, action, args=None):
        root = self._root()
        return self._spawn(lambda: GitTools(root).action(action, args or {}), kind='git_result')

    @guarded
    def approval_response(self, id, approved):
        with self.lock:
            box = self.approvals.get(id)
            if box:
                box['approved'] = bool(approved)
                box['event'].set()
        return {'ok': bool(box)}

    @guarded
    def agent_rules_get(self):
        return {'ok': True, **self.config.rules_get()}

    @guarded
    def agent_rules_set(self, rules, on=True):
        return {'ok': True, **self.config.rules_set(rules, on)}

    @guarded
    def agent_rules_reset(self):
        return {'ok': True, **self.config.rules_reset()}

    @guarded
    def agent_rules_preview(self, text=''):
        return {'ok': True, 'text': self.config.rules_preview(text, self.project['path'] if self.project else 'my project')}

    @guarded
    def file_upload(self, name, mime, data_url, platform):
        content = decode_data(data_url)
        ident = uuid.uuid4().hex
        self.bridge.send({'type': 'file_upload', 'id': ident, 'name': Path(name).name,
                          'mime': mime or mimetypes.guess_type(name)[0] or 'text/plain',
                          'data_url': data_url, 'platform': platform})
        return {'ok': True, 'id': ident, 'size': len(content)}

    @guarded
    def file_fetch(self, url, name, platform):
        ident = uuid.uuid4().hex
        self.bridge.send({'type': 'file_fetch', 'id': ident, 'url': url, 'name': name, 'platform': platform})
        return {'ok': True, 'id': ident}

    @guarded
    def file_save(self, name, data_url):
        content = decode_data(data_url)
        safe_name = Path(name.replace('\\', '/')).name
        if safe_name in ('', '.', '..'):
            raise ValueError('Invalid file name')
        def save():
            import webview
            chosen = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=safe_name)
            if not chosen:
                return {'ok': False, 'error': 'Save cancelled'}
            destination = Path(chosen[0] if isinstance(chosen, (list, tuple)) else chosen)
            destination.write_bytes(content)
            return {'path': str(destination), 'bytes': len(content)}
        return self._spawn(save, kind='file_saved')

    @guarded
    def logs_reveal(self):
        target = self.base / "logs"
        target.mkdir(parents=True, exist_ok=True)
        def open_dir():
            if os.name == "nt":
                subprocess.Popen(["explorer", str(target)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
            return {"ok": True, "path": str(target)}
        return self._spawn(open_dir, kind="logs_revealed")

    @guarded
    def logs_get(self):
        directory = self.base / 'logs'
        files = sorted(directory.glob('*.log'))
        lines = []
        events = directory / 'chatbridge-events.log'
        if events.is_file(): files.append(events)
        for path in files[-4:]:
            with path.open('rb') as file:
                file.seek(max(0, path.stat().st_size - 200000))
                lines.extend(file.read().decode('utf-8', errors='replace').splitlines())
        return {'ok': True, 'lines': lines[-500:]}

    @guarded
    def logs_export(self):
        def export():
            destination = self.base / ('logs-' + time.strftime('%Y%m%d-%H%M%S') + '.zip')
            with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
                for path in (self.base / 'logs').glob('*.log'):
                    archive.write(path, path.name)
            return {'path': str(destination)}
        return self._spawn(export, kind='logs_exported')

    def _start_provider(self):
        config = self.config.get()
        self.provider = ProviderServer(self.bridge, config['provider_key'], config.get('provider_port', 8788),
                                       config.get('provider_timeout', 600)).start()

    @guarded
    def provider_set(self, enabled, port=8788):
        self.config.update({'provider_enabled': bool(enabled), 'provider_port': int(port)})
        def apply():
            if self.provider:
                self.provider.stop()
                self.provider = None
            if enabled:
                self._start_provider()
            return {'enabled': bool(self.provider), 'port': int(port)}
        return self._spawn(apply, kind='provider_status')


def acquire_single_instance(base):
    """Return ('ok', handle), ('held', None), or ('error', None).

    Two copies of ChatBridge used to fail much later and much less clearly:
    the second one could not bind the WebSocket port and the user only saw
    'WinError 10048' in the browser log. Locking a per-user file up front
    turns that into one message. The handle stays open for the whole
    process; the OS releases the lock when the process exits.
    """
    path = base / 'instance.lock'
    try:
        handle = open(path, 'a+b')
    except OSError:
        return 'error', None
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return 'held', None
    try:
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()).encode('ascii'))
        handle.flush()
    except OSError:
        pass
    return 'ok', handle


def main():
    if '--version' in sys.argv:
        print(APP_VERSION)
        return 0
    if os.name != 'nt' and '--allow-nonwindows' not in sys.argv:
        print('ChatBridge targets Windows 10/11 x64. Source checks work here; use --allow-nonwindows for experimental Qt/GTK desktop mode.')
        return 0
    try:
        import webview
    except ImportError:
        print('Install desktop dependencies: python -m pip install -r requirements.txt')
        return 1
    base = default_data_dir()
    base.mkdir(parents=True, exist_ok=True)
    lock_state, _lock = acquire_single_instance(base)
    if lock_state == 'held':
        message = ('ChatBridge is already running.\n\n'
                   'Close the existing window (or end ChatBridge in Task Manager) '
                   'and start ChatBridge again.')
        if os.name == 'nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, 'ChatBridge', 0x40)
        else:
            print(message)
        return 1
    directory = base / 'logs'
    directory.mkdir(parents=True, exist_ok=True)
    from logging.handlers import RotatingFileHandler
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s',
                        handlers=[RotatingFileHandler(directory/'chatbridge.log', maxBytes=2*1024*1024,
                                                      backupCount=4, encoding='utf-8')])
    config = ConfigStore(base)
    profile = profile_path()
    if config.get().get('reset_profile_next_start'):
        import shutil
        if profile.exists():
            shutil.rmtree(profile)
        config.update({'reset_profile_next_start': False})
    profile.mkdir(parents=True, exist_ok=True)
    os.environ['WEBVIEW2_USER_DATA_FOLDER'] = str(profile)
    api = Api(base)
    ui = Path(__file__).parent / 'ui' / 'index.html'
    if not ui.is_file():
        # PyInstaller one-file extracts resources under _MEIPASS. Keep the
        # failure explicit instead of letting pywebview return a confusing
        # localhost:port/index.html 404 page.
        extracted = Path(getattr(sys, '_MEIPASS', '')) / 'desktop' / 'ui' / 'index.html'
        if extracted.is_file():
            ui = extracted
        else:
            print(f'ChatBridge UI resource is missing: {ui}')
            return 1
    window = webview.create_window('ChatBridge ' + APP_VERSION, url=ui.resolve().as_uri(), js_api=api,
                                   width=1440, height=940, min_size=(1000, 680),
                                   background_color='#11151d', text_select=True)
    api._window = window
    api._browser.main_window = window
    window.events.closed += api.shutdown
    webview.start(api.start, private_mode=False, storage_path=str(profile),
                  gui='edgechromium' if os.name == 'nt' else None, debug='--debug' in sys.argv)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
