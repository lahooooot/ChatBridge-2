"""One companion webview, native child docking, and one authenticated WS driver."""
from __future__ import annotations
import asyncio
import base64
import ctypes
import json
import logging
import os
import queue
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
from .toolparse import parse_tool_calls, has_unterminated
from .config import DATA_DIR_NAME

log = logging.getLogger(__name__)
VERSION = '2.60.0'
MAX_TOOL_ROUNDS = 24
PLATFORM_HOME = {'chatgpt': 'https://chatgpt.com/', 'claude': 'https://claude.ai/',
                 'zai': 'https://chat.z.ai/', 'deepseek': 'https://chat.deepseek.com/',
                 'gemini': 'https://gemini.google.com/app'}
ERROR_TEXT = re.compile(r'no response.*try again|something went wrong|syntaxerror: unexpected token|خطایی رخ داد|دوباره تلاش کنید', re.I)


def same_conversation(a, b):
    return bool(a and b) and urlparse(a).netloc == urlparse(b).netloc and (
        urlparse(a).path.rstrip('/').split('/')[-1] == urlparse(b).path.rstrip('/').split('/')[-1])


def profile_path():
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ChatBridge' / DATA_DIR_NAME.lstrip('.') / 'WebView2'
    return Path.home() / DATA_DIR_NAME / 'WebView2'


class NativeDock:
    """Use real client pixels / CSS client size, not a guessed DPI constant."""
    def __init__(self, parent, child):
        self.parent = parent
        self.child = child
        self.docked = False
        self.user32 = None
        self.parent_hwnd = None
        self.child_hwnd = None

    @staticmethod
    def handle(window):
        native = window.native
        handle = getattr(native, 'Handle', None)
        if handle is not None:
            return int(handle.ToInt64()) if hasattr(handle, 'ToInt64') else int(handle)
        raise RuntimeError('Native window handle is not available')

    def mount(self):
        if os.name != 'nt':
            raise RuntimeError('Win32 docking is available only on Windows')
        from ctypes import wintypes
        u = ctypes.WinDLL('user32', use_last_error=True)
        u.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
        u.SetParent.restype = wintypes.HWND
        getter = getattr(u, 'GetWindowLongPtrW', u.GetWindowLongW)
        setter = getattr(u, 'SetWindowLongPtrW', u.SetWindowLongW)
        getter.argtypes = [wintypes.HWND, ctypes.c_int]
        getter.restype = ctypes.c_ssize_t
        setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        setter.restype = ctypes.c_ssize_t
        u.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.BOOL]
        u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        parent, child = self.handle(self.parent), self.handle(self.child)
        ctypes.set_last_error(0)
        old = u.SetParent(child, parent)
        if not old and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        style = getter(child, -16)
        setter(child, -16, (style | 0x40000000) & ~0x80000000 & ~0x00C00000)
        exstyle = getter(child, -20)
        setter(child, -20, (exstyle | 0x80) & ~0x40000)
        setter(parent, -16, getter(parent, -16) | 0x02000000)  # clip native children
        u.SetWindowPos(child, None, 0, 0, 0, 0, 0x33)  # HWND_TOP, frame changed, no activate
        self.user32, self.parent_hwnd, self.child_hwnd = u, parent, child
        self.docked = True

    def fit(self, x, y, w, h, visible, cw, ch):
        if not self.docked:
            return
        from ctypes import wintypes
        rect = wintypes.RECT()
        if not self.user32.GetClientRect(self.parent_hwnd, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        sx = (rect.right - rect.left) / max(float(cw), 1)
        sy = (rect.bottom - rect.top) / max(float(ch), 1)
        self.user32.MoveWindow(self.child_hwnd, round(x * sx), round(y * sy),
                               max(1, round(w * sx)), max(1, round(h * sy)), True)
        self.user32.ShowWindow(self.child_hwnd, 4 if visible and w > 5 and h > 5 else 0)


class InternalBrowser:
    def __init__(self, bridge, sink, homes=None):
        self.bridge, self.sink = bridge, sink
        self.homes = dict(PLATFORM_HOME)
        self.homes.update(homes or {})
        self.main_window = None
        self.window = None
        self.dock = None
        self.platform = 'chatgpt'
        self._closing = threading.Event()
        self._loaded = threading.Event()
        self._creating = threading.Lock()
        self._eval_lock = threading.Lock()
        self._geometry = None
        self._driver_started = False
        self._ws = None
        self._stopped = {}
        self._stop_events = {}
        self._rounds = {}
        self._active = None
        self._agent = Path(__file__).with_name('agent_cb.js')
        # Callable(host) -> {editor:[...], send:[...], ...}. Set by app.py so a
        # standalone platform_hints.json can drive unknown sites.
        self.hints_provider = None
        # Callable(host, reason, observed) used to remember failure evidence.
        self.hint_recorder = None

    def _trace(self, message, **fields):
        """Send bounded diagnostic metadata to both file log and the UI log."""
        safe = {k: fields[k] for k in fields if k not in {'text', 'prompt', 'response', 'content'}}
        detail = message + ((' ' + json.dumps(safe, ensure_ascii=False, default=str)) if safe else '')
        log.info('[driver] %s', detail)
        self.sink({'type': 'browser_log', 'text': detail})

    def open(self, platform='chatgpt'):
        threading.Thread(target=self._open_worker, args=(platform,), daemon=True,
                         name='browser-create').start()

    def _open_worker(self, platform):
        with self._creating:
            # Capture the site the existing window is on before overwriting it,
            # so a model switch can really navigate instead of only updating the
            # URL bar in the UI.
            previous = self.platform
            self.platform = platform
            try:
                if not self.window:
                    import webview
                    self._loaded.clear()
                    self.window = webview.create_window('ChatBridge Internal Browser',
                        url=self.homes.get(platform, self.homes['chatgpt']), hidden=True,
                        frameless=True, easy_drag=False, width=700, height=750)
                    self.window.events.loaded += self._on_loaded
                    self.window.events.closed += self._on_closed
                    # A loaded event may race with registering the handler.
                    threading.Thread(target=self._late_ready, daemon=True).start()
                    if self.main_window:
                        try:
                            self.window.events.shown.wait(0.1)
                        except Exception:
                            pass
                        for _ in range(50):
                            try:
                                self.dock = NativeDock(self.main_window, self.window)
                                self.dock.mount()
                                if self._geometry:
                                    self.dock.fit(*self._geometry)
                                break
                            except Exception as exc:
                                if os.name != 'nt':
                                    break
                                time.sleep(0.1)
                        if not self.dock or not self.dock.docked:
                            log.warning('Native dock unavailable; recovering in floating window')
                            self.window.show()
                            self.sink({'type': 'browser_status', 'floating': True,
                                       'error': 'Native docking failed; floating recovery is active.'})
                    if not self._driver_started:
                        self._driver_started = True
                        threading.Thread(target=lambda: asyncio.run(self._driver()),
                                         daemon=True, name='internal-driver').start()
                else:
                    if self._geometry:
                        self.fit(*self._geometry)
                    if not self.dock or not self.dock.docked:
                        self.window.show()
                    # Changing the model in the header must open the new
                    # platform's site. The window is reused, so nothing else
                    # navigates it and the old page would stay on screen.
                    if platform != previous:
                        self._loaded.clear()
                        home = self.homes.get(platform, PLATFORM_HOME['chatgpt'])
                        self.window.load_url(home)
                        threading.Thread(target=self._late_ready, daemon=True,
                                         name='agent-late-ready').start()
            except Exception as exc:
                log.exception('Internal browser creation failed')
                self.sink({'type': 'error', 'source': 'browser', 'error': str(exc)})

    def _late_ready(self):
        # WebView2 sometimes drops the 'loaded' event (or fires it before the
        # agent can be injected) for SPA navigations like z.ai / deepseek.
        # Retry a few times so _loaded eventually gets set and _ensure()
        # doesn't time out with 'no-tab'.
        for delay in (3, 4, 6):
            time.sleep(delay)
            if self._loaded.is_set():
                return
            self.reinject()

    def _on_loaded(self, *args):
        # Never wait in WebView's loaded callback.
        self._loaded.clear()
        threading.Thread(target=self._inject, daemon=True, name='agent-inject').start()

    def _on_closed(self, *args):
        self.window = None
        self._loaded.clear()

    def _inject(self):
        try:
            prefix = ''
            if self.hints_provider:
                try:
                    host = urlparse(self.window.get_current_url() or '').hostname or ''
                    hint_map = self.hints_provider(host) if host else {}
                except Exception:
                    hint_map = {}
                if hint_map:
                    prefix = 'window.__CB_HOST_HINTS__ = %s;\n' % json.dumps(hint_map, ensure_ascii=False)
            result = self.evaluate(prefix + self._agent.read_text(encoding='utf-8'), timeout=12)
            # Agent script is installed — the bridge can deliver commands now.
            # Page readiness (editor/send) is verified separately by waitReady()
            # in _turn(), so probe/snap here are purely diagnostic and must
            # never stop _loaded from being set (z.ai/deepseek SPAs are slow).
            self._loaded.set()
            try:
                probe = self.call('probe', timeout=8)
                page = self.call('snap', timeout=8) or {}
                log.info('Agent injected platform=%s probe=%s result=%s', self.platform, probe, result)
                self.sink({'type': 'browser_log', 'text': 'Agent injected: ' + json.dumps(probe, ensure_ascii=False)})
                self.sink({'type': 'browser_status', 'connected': self.bridge.connected,
                           'browser_open': True, 'page_url': page.get('url', '')})
            except Exception as inner:
                log.debug('Agent probe failed: %s', inner)
                self.sink({'type': 'browser_log', 'text': 'Agent injected; probe failed: ' + str(inner)})
        except Exception as exc:
            log.warning('Agent injection failed: %s', exc)
            self.sink({'type': 'browser_log', 'text': 'Agent injection failed: ' + str(exc)})
            # Some pages throw on early injection; retry the agent install.
            threading.Timer(4.0, self.reinject).start()

    def evaluate(self, script, timeout=10, guard=None):
        if not self.window:
            # A closed browser can still hold a stale lock from an orphaned
            # call. Clear it before raising so reopening is not wedged.
            if not self._eval_lock.acquire(timeout=min(timeout, 5)):
                self._force_release_eval_lock()
            else:
                self._eval_lock.release()
            raise RuntimeError('Internal browser is closed')
        # Cap the wait so a hung earlier call cannot stall the model switch
        # or sidebar navigation for the whole per-request timeout. If the
        # lock is held past this bound, the holder is almost certainly an
        # orphaned native evaluate; break it so the retry can proceed.
        if not self._eval_lock.acquire(timeout=min(timeout, 5)):
            log.warning('Breaking stale WebView eval lock (previous call hung)')
            self._force_release_eval_lock()
            if not self._eval_lock.acquire(timeout=1):
                raise TimeoutError('Previous WebView script is still blocked')
        result, done = {}, threading.Event()
        window = self.window
        def complete(value):
            result['value'] = value
            done.set()
        def worker():
            try:
                if guard is not None and not guard():
                    complete({'ok': False, 'error': 'request-no-longer-active'})
                    return
                # callback resolves promises; direct evaluate_js would serialize Promise as {}.
                value = window.evaluate_js(script, callback=complete)
                if value is not None and not done.is_set():
                    complete(value)
            except Exception as exc:
                result['error'] = exc
                done.set()
            finally:
                # Release only when native evaluate_js returns. Hung native calls block
                # later evaluations instead of creating unlimited blocked threads.
                # Best-effort release: the timeout path may already have
                # force-released this lock, so double-release is harmless.
                self._force_release_eval_lock()
        threading.Thread(target=worker, daemon=True, name='webview-eval').start()
        if not done.wait(timeout):
            # A native evaluate_js can be orphaned when the page navigates
            # away from the JS context mid-call. Force-release the lock so
            # the next retry does not fail with "still blocked" forever.
            self._force_release_eval_lock()
            raise TimeoutError('WebView script timed out')
        if 'error' in result:
            raise result['error']
        return result.get('value')

    def _force_release_eval_lock(self):
        """Release _eval_lock even if an orphaned worker still holds it.

        pywebview's evaluate_js can hang forever when the page navigates
        away mid-call. A plain Lock then stays held, and every later call
        fails with 'Previous WebView script is still blocked' -- which is
        exactly the failure the model switch and sidebar clicks hit. We
        accept the small risk of two overlapping native calls (WebView2
        serializes them anyway) so the browser recovers on the next retry.
        """
        try:
            self._eval_lock.release()
        except RuntimeError:
            pass

    def call(self, method, *args, timeout=12):
        script = '(async()=>{try{if(!window.__CB__)return {ok:false,error:"agent-not-ready"};return await window.__CB__[%s](...%s)}catch(e){return {ok:false,error:String(e)}}})()' % (
            json.dumps(method), json.dumps(args, ensure_ascii=False))
        return self.evaluate(script, timeout)

    def fit(self, *geometry):
        self._geometry = geometry
        def apply():
            try:
                if self.dock:
                    self.dock.fit(*geometry)
            except Exception as exc:
                log.warning('Dock geometry error: %s', exc)
        threading.Thread(target=apply, daemon=True).start()

    def close(self):
        self.stop_request(self._active or '')
        window = self.window
        if window:
            threading.Thread(target=window.destroy, daemon=True).start()

    def shutdown(self):
        self._closing.set()
        self.close()

    def reinject(self):
        threading.Thread(target=self._inject, daemon=True).start()

    def set_overlay(self, active):
        """Temporarily hide the native child window so HTML modals stay on top.

        The docked browser is a real Win32 child window; it always paints above
        the pywebview UI, so an HTML <dialog> would appear behind it.
        """
        try:
            if self.dock and self.dock.docked and self._geometry:
                x, y, w, h, visible, cw, ch = self._geometry
                self.dock.fit(x, y, w, h, bool(visible) and not active, cw, ch)
            elif self.window:
                # Floating fallback: the whole webview is a normal window.
                if active:
                    try: self.window.hide()
                    except Exception: pass
                else:
                    try: self.window.show()
                    except Exception: pass
            return {'ok': True, 'hidden': bool(active)}
        except Exception as exc:
            return {'ok': False, 'error': str(exc)}

    def navigate_and_wait(self, url, host='', timeout=30):
        """Load a URL and wait until the live hostname matches (or time out).

        A stale _loaded flag from the previous page is not enough: we read the
        real URL from the page before deciding the navigation finished.
        """
        if not self.window:
            return {'ok': False, 'error': 'no-window'}
        try:
            snap = self.call('snap', timeout=8) or {}
        except Exception:
            snap = {}
        current = (urlparse(snap.get('url', '')).hostname or '').lower()
        if host and current == host:
            return {'ok': True, 'url': snap.get('url', ''), 'already': True}
        try:
            self._loaded.clear()
            self.window.load_url(url)
            threading.Thread(target=self._late_ready, daemon=True, name='agent-late-ready').start()
        except Exception as exc:
            return {'ok': False, 'error': str(exc)}
        deadline = time.time() + timeout
        last = ''
        while time.time() < deadline:
            try:
                snap = self.call('snap', timeout=8) or {}
            except Exception:
                snap = {}
            last = snap.get('url', '')
            current = (urlparse(last).hostname or '').lower()
            if current and (not host or current == host):
                return {'ok': True, 'url': last}
            time.sleep(0.5)
        return {'ok': False, 'error': 'nav-timeout', 'url': last, 'want_host': host}

    def pick_now(self, mode):
        """Turn on the in-page element picker; the click arrives as an event."""
        try:
            return self.call('pick', mode, timeout=10) or {'ok': False, 'error': 'no-result'}
        except Exception as exc:
            return {'ok': False, 'error': str(exc)}

    def detect_now(self, host=''):
        """Structural probe of the page the user just signed in to.

        Returns editor/send candidates with stable CSS paths. Never types
        anything, so it is safe to run on a live conversation.
        """
        try:
            if not self._loaded.wait(20):
                return {'ok': False, 'error': 'page-not-ready', 'host': host}
            # _loaded can belong to the previous page while a navigation is still
            # in flight. Confirm the live URL is really this host before probing.
            deadline = time.time() + 20
            current = ''
            while time.time() < deadline:
                try:
                    snap = self.call('snap', timeout=8) or {}
                except Exception:
                    snap = {}
                current = (urlparse(snap.get('url', '')).hostname or '').lower()
                if host and current and current == host:
                    break
                time.sleep(0.5)
            if host and current and current != host:
                return {'ok': False, 'error': 'wrong-page', 'host': host, 'page_host': current}
            result = self.call('detect', timeout=20) or {}
        except Exception as exc:
            return {'ok': False, 'error': str(exc), 'host': host}
        if self.hint_recorder and isinstance(result, dict):
            try:
                self.hint_recorder(host or result.get('host', ''), 'detect', result)
            except Exception:
                pass
        return result

    def navigate(self, action, url=''):
        def run():
            try:
                if action == 'navigate':
                    if urlparse(url).scheme not in ('http', 'https'):
                        raise ValueError('Only HTTP and HTTPS navigation is allowed')
                    self._loaded.clear()
                    self.window.load_url(url)
                    threading.Thread(target=self._late_ready, daemon=True,
                                     name='agent-late-ready').start()
                    self.sink({'type': 'browser_status', 'connected': self.bridge.connected,
                               'browser_open': True, 'page_url': url, 'url': url})
                elif action == 'back':
                    self.evaluate('history.back(); true')
                elif action == 'forward':
                    self.evaluate('history.forward(); true')
                elif action == 'reload':
                    self.evaluate('location.reload(); true')
                else:
                    raise ValueError('Unknown browser action')
            except Exception as exc:
                self.sink({'type': 'error', 'source': 'browser', 'error': str(exc)})
        threading.Thread(target=run, daemon=True).start()

    def stop_request(self, request_id):
        if request_id and self.stopped(request_id):
            return
        if request_id:
            self._stopped[request_id] = time.monotonic() + 300
        if self._active == request_id or (not request_id and self._active is None):
            self._stop_events[request_id] = threading.Event()
            threading.Thread(target=self._quiet_stop, args=(request_id,), daemon=True).start()

    def _quiet_stop(self, request_id):
        try:
            self.evaluate('window.__CB__ ? window.__CB__.stop() : {ok:false}', timeout=5,
                          guard=lambda: self._active == request_id or (not request_id and self._active is None))
        except Exception:
            pass
        finally:
            done = self._stop_events.get(request_id)
            if done:
                done.set()

    def stopped(self, rid):
        now = time.monotonic()
        self._stopped = {k: v for k, v in self._stopped.items() if v > now}
        self._stop_events = {k: v for k, v in self._stop_events.items() if k in self._stopped or not k}
        return rid in self._stopped

    async def _emit(self, kind, **fields):
        if self._ws:
            await self._ws.send(json.dumps({'type': kind, **fields}, ensure_ascii=False))

    async def _call(self, method, *args, timeout=12):
        return await asyncio.to_thread(self.call, method, *args, timeout=timeout)

    async def _ensure(self, platform, url=None, fresh=False):
        if not self.window:
            self.open(platform)
        if not await asyncio.to_thread(self._loaded.wait, 25):
            raise RuntimeError('no-tab')
        snap = await self._call('snap') or {}
        home = self.homes.get(platform)
        target = home if fresh else (url or home)
        if target and (fresh or urlparse(snap.get('url', '')).netloc != urlparse(target).netloc or
                       (url and not same_conversation(snap.get('url'), url))):
            navigated = None
            if not fresh and url and urlparse(snap.get('url', '')).netloc == urlparse(target).netloc:
                navigated = await self._call('navigate', target, timeout=8) or {}
            if not navigated or not navigated.get('ok'):
                self._loaded.clear()
                await asyncio.to_thread(self.window.load_url, target)
                threading.Thread(target=self._late_ready, daemon=True,
                                 name='agent-late-ready').start()
                if not await asyncio.to_thread(self._loaded.wait, 25):
                    raise RuntimeError('Navigation did not finish')
            elif navigated.get('how') == 'location':
                await asyncio.sleep(2)
                if not await asyncio.to_thread(self._loaded.wait, 25):
                    raise RuntimeError('Navigation did not finish')
            await asyncio.sleep(1.4)
        self.platform = platform
        await self._emit('cs_ready', platform=platform, page_url=(await self._call('snap') or {}).get('url'))

    async def _wait_idle(self, platform, rid, seconds=45):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not self.stopped(rid):
            snap = await self._call('snap') or {}
            if not snap.get('busy'):
                return True
            await self._emit('assistant_waiting', platform=platform, request_id=rid,
                             waited_ms=0, has_text=False, stage='waiting')
            await asyncio.sleep(1)
        return False

    async def _capture(self, platform, rid, before, timeout):
        start = changed = heartbeat = stream_at = time.monotonic()
        last, sent, moved, fence_idle = '', '', False, None
        stable_ms = 1.5 if platform in ('zai', 'deepseek') else 1.1
        previous_stage = None
        final = {}
        while time.monotonic() - start < timeout:
            if self.stopped(rid):
                return None
            try:
                snap = await self._call('snap', timeout=8) or {}
            except Exception:
                await asyncio.sleep(0.2)
                continue
            now = time.monotonic()
            text = str(snap.get('text', ''))[:200000]
            count = snap.get('count', 0)
            # Reject old text until a new unit or a changed current-turn body appears.
            if count > before.get('count', 0) or (text and text != before.get('text', before.get('last', ''))):
                moved = True
            if text != last:
                changed, last = now, text
            stage = snap.get('stage', 'writing' if text else 'waiting')
            if moved and text != sent and now - stream_at >= 0.5:
                await self._emit('assistant_stream', platform=platform, request_id=rid, text=text,
                                 think=snap.get('think'), think_active=snap.get('think_active'),
                                 page_url=snap.get('url'))
                sent, stream_at = text, now
            if now - heartbeat >= 5 or stage != previous_stage:
                await self._emit('assistant_waiting', platform=platform, request_id=rid,
                                 waited_ms=int((now-start)*1000), has_text=bool(moved and text), stage=stage)
                heartbeat, previous_stage = now, stage
            opened = has_unterminated(text)
            if opened and not snap.get('busy'):
                fence_idle = fence_idle or now
            else:
                fence_idle = None
            stable = now - changed >= stable_ms
            if moved and text and stable and not snap.get('busy') and (
                    not opened or (fence_idle and now-fence_idle >= 10)):
                final = snap
                break
            final = snap
            await asyncio.sleep(0.2)
        if self.stopped(rid):
            return None
        text = str(final.get('text', ''))[:200000]
        if not moved or (text == before.get('text', before.get('last', '')) and
                         final.get('count', 0) <= before.get('count', 0)):
            return {'failure': 'stale' if text else 'empty'}
        if not text.strip():
            return {'failure': 'empty'}
        if text != sent:
            await self._emit('assistant_stream', platform=platform, request_id=rid, text=text,
                             think=final.get('think'), page_url=final.get('url'))
        return final

    async def _turn(self, packet, text, attachment=None, tool_ids=None):
        platform, rid = packet.get('platform', self.platform), packet['request_id']
        if self.stopped(rid):
            return
        self._active = rid
        self._trace('turn-start', request_id=rid[:12], platform=platform, text_length=len(text),
                    has_attachment=bool(attachment), tool_count=len(tool_ids or []))
        try:
            await self._ensure(platform, packet.get('conv_url'), bool(packet.get('fresh')))
            ready = await self._call('waitReady', 90000 if platform in ('deepseek', 'zai') else 30000, timeout=95)
            self._trace('page-ready', request_id=rid[:12], platform=platform,
                        ready=bool(ready and ready.get('ready')), editor=bool(ready and ready.get('editor')),
                        send=bool(ready and ready.get('send')))
            if not ready or not ready.get('ready'):
                await self._emit('prompt_error', platform=platform, request_id=rid,
                                 reason='send-failed', detail='The web composer is not ready.', probe=ready)
                return
            if not await self._wait_idle(platform, rid, 90 if platform == 'zai' else 45):
                await self._emit('prompt_error', platform=platform, request_id=rid, reason='send-failed')
                return
            if attachment:
                # Put the message text in the composer FIRST, then attach the
                # file, so the text is never wiped by the upload step.
                # WebView2/pywebview may unwrap an object result to a bool, so
                # never call .get() on it directly.
                typed = await self._call('type', text, timeout=30)
                typed_ok = bool(typed) if isinstance(typed, bool) else bool(isinstance(typed, dict) and typed.get('ok'))
                self._trace('typed', request_id=rid[:12], ok=typed_ok, raw_type=type(typed).__name__)
                raw_upload = await self._call('upload', attachment['name'], attachment['mime'], attachment['data_url'], timeout=90)
                result = raw_upload if isinstance(raw_upload, dict) else {'ok': bool(raw_upload), 'raw_type': type(raw_upload).__name__}
                self._trace('upload-result', request_id=rid[:12], raw_type=type(raw_upload).__name__, ok=bool(result.get('ok')))
                if not result or not result.get('ok'):
                    await self._emit('prompt_error', platform=platform, request_id=rid, reason='attach-failed')
                    return
                # Some sites clear the composer when a file is attached. If the
                # text is gone, type it again so it is submitted with the file.
                after = await self._call('snap') or {}
                if not str(after.get('composer', '') or '').strip():
                    retyped = await self._call('type', text, timeout=30)
                    re_ok = bool(retyped) if isinstance(retyped, bool) else bool(isinstance(retyped, dict) and retyped.get('ok'))
                    self._trace('retyped-after-upload', request_id=rid[:12], ok=re_ok)
            before = await self._call('snap') or {}
            await self._call('baseline')
            self._trace('before-send', request_id=rid[:12], count=before.get('count', 0),
                        text_length=len(str(before.get('text', ''))), busy=bool(before.get('busy')))
            raw_send = (await self._call('submit', timeout=90)) if attachment else (await self._call('send', text, timeout=65))
            # Some WebView2/pywebview callback paths unwrap an object-shaped
            # JS result to a boolean. True still means the page accepted the
            # click; normalize it instead of crashing on ``send.get``.
            if isinstance(raw_send, dict):
                send = raw_send
            elif isinstance(raw_send, bool):
                send = {'ok': raw_send, 'verdict': 'accepted' if raw_send else 'stuck',
                        'how': 'webview-bool-result', 'error': None}
            else:
                send = {'ok': False, 'verdict': 'stuck', 'error': f'unexpected-send-result:{type(raw_send).__name__}'}
            self._trace('send-result', request_id=rid[:12], raw_type=type(raw_send).__name__,
                        ok=bool(send.get('ok')), verdict=send.get('verdict'),
                        how=send.get('how'), error=send.get('error'))
            verdict = send.get('verdict', 'accepted' if send.get('ok') else 'stuck')
            if tool_ids:
                await self._emit('tool_delivery', platform=platform, request_id=rid, count=len(tool_ids),
                                 tools=tool_ids, verdict='sent' if verdict == 'accepted' else verdict, ok=bool(send.get('ok')))
            if not send.get('ok'):
                reason = 'send-dropped' if verdict == 'dropped' else ('no-input' if send.get('error') == 'no-input' else 'send-failed')
                await self._emit('prompt_error', platform=platform, request_id=rid, reason=reason)
                if verdict == 'dropped':
                    return
                # A stuck composer still captures a user's manual Enter.
            timeout = 300 if platform in ('zai', 'deepseek') else 180
            answer = await self._capture(platform, rid, before, timeout)
            self._trace('capture-result', request_id=rid[:12], ok=bool(answer and not answer.get('failure')),
                        failure=(answer or {}).get('failure'), text_length=len(str((answer or {}).get('text', ''))))
            if answer is None:
                return
            if not attachment and (answer.get('failure') == 'empty' or ERROR_TEXT.search(answer.get('text', ''))) and not self.stopped(rid):
                if await self._wait_idle(platform, rid, 45) and not self.stopped(rid):
                    retry_before = await self._call('snap') or {}
                    await self._call('baseline')
                    retry = await self._call('send', text, timeout=65) or {}
                    if retry.get('ok'):
                        answer = await self._capture(platform, rid, retry_before, 90)
            if answer is None or self.stopped(rid):
                return
            if answer.get('failure'):
                log.warning('Capture failed %s probe=%s', answer, await self._call('probe'))
                await self._emit('assistant_capture_failed', platform=platform, request_id=rid, reason=answer['failure'])
                return
            if tool_ids:
                await self._emit('tool_delivery', platform=platform, request_id=rid, count=len(tool_ids),
                                 tools=tool_ids, verdict='accepted', ok=True)
            calls = parse_tool_calls(answer.get('text', ''))
            round_count = self._rounds.get(rid, 0)
            continuation = bool(calls) and round_count < MAX_TOOL_ROUNDS and not rid.startswith('prov-')
            await self._emit('assistant_response', platform=platform, request_id=rid,
                             text=str(answer.get('text', ''))[:200000], think=answer.get('think'),
                             page_url=answer.get('url'), files=answer.get('files', []), parsed_calls=calls,
                             continuation_pending=continuation)
            if rid.startswith('prov-'):
                return
            if calls and round_count < MAX_TOOL_ROUNDS:
                self._rounds[rid] = round_count + 1
                for call in calls:
                    await self._emit('tool_call', **call, platform=platform, request_id=rid,
                                     page_url=answer.get('url'))
            elif calls:
                await self._emit('tool_budget', request_id=rid, platform=platform,
                                 error='Tool budget reached. Finish with a concise summary; no more tools will run.')
                # Give the model one closing turn with no tools so the user gets
                # a final answer instead of a stuck request.
                if not self.stopped(rid):
                    close_text = ('The local tool budget for this message is now exhausted. '
                                  'Do not request any more tools. Reply with a short, complete summary '
                                  'of what you did and any remaining steps.')
                    close_before = await self._call('snap') or {}
                    await self._call('baseline')
                    closing = await self._call('send', close_text, timeout=65) or {}
                    if closing.get('ok'):
                        answer = await self._capture(platform, rid, close_before, 120)
                        if answer and not answer.get('failure'):
                            await self._emit('assistant_response', platform=platform, request_id=rid,
                                             text=str(answer.get('text', ''))[:200000], think=answer.get('think'),
                                             page_url=answer.get('url'), files=answer.get('files', []),
                                             parsed_calls=[], continuation_pending=False)
        except Exception as exc:
            log.exception('Browser turn failed')
            self._trace('turn-exception', request_id=rid[:12], error=str(exc), window=bool(self.window))
            await self._emit('prompt_error', platform=platform, request_id=rid,
                             reason='no-tab' if not self.window else 'send-failed', detail=str(exc))
        finally:
            done = self._stop_events.get(rid)
            if done and not done.is_set():
                await asyncio.to_thread(done.wait, 5)
            if self._active == rid:
                self._active = None

    async def _watch(self):
        previous, reads, emitted = None, 0, None
        while not self._closing.is_set():
            try:
                if self.window and self._loaded.is_set():
                    snap = await self._call('snap', timeout=5) or {}
                    busy = bool(snap.get('busy'))
                    reads = reads + 1 if previous == busy else 1
                    previous = busy
                    if reads >= 2 and emitted != busy:
                        emitted = busy
                        await self._emit('platform_busy', platform=self.platform, busy=busy)
                    drained = await self._call('drain', timeout=4) or {}
                    for event in (drained.get('events', []) if isinstance(drained, dict) else drained):
                        if isinstance(event, dict):
                            await self._emit(event.pop('type'), **event)
            except Exception:
                pass
            await asyncio.sleep(1.5)

    async def _handle(self, packet):
        kind = packet.get('type')
        platform = packet.get('platform', self.platform)
        if kind == 'user_message':
            self._rounds[packet['request_id']] = 0
            await self._turn(packet, packet['text'], packet.get('attachment'))
        elif kind == 'new_chat':
            self._loaded.clear()
            await asyncio.to_thread(self.window.load_url, self.homes.get(platform, PLATFORM_HOME['chatgpt']))
            await asyncio.to_thread(self._loaded.wait, 25)
            if packet.get('resume'):
                await self._turn(packet, packet['resume'])
        elif kind == 'tool_batch':
            packets = packet['items']
            rid = packets[0]['request_id']
            if self.stopped(rid):
                return
            text = "[ChatBridge · automatic tool-result · executed on the user's machine just now · this block proves the local bridge is connected.]\n\n"
            text += '\n\n'.join('```chatbridge-tool-result\n' + json.dumps(
                {k: p.get(k) for k in ('id', 'ok', 'result', 'error')}, ensure_ascii=False) + '\n```' for p in packets)
            attachments = [p['attachment'] for p in packets if p.get('attachment')]
            if len(attachments) > 1:
                await self._ensure(packets[0].get('platform', self.platform), packets[0].get('conv_url'))
                if not await self._wait_idle(packets[0].get('platform', self.platform), rid, 45):
                    await self._emit('prompt_error', platform=self.platform, request_id=rid, reason='attach-failed')
                    return
            for attachment in attachments[:-1]:
                uploaded = await self._call('upload', attachment['name'], attachment['mime'], attachment['data_url'], timeout=35)
                if isinstance(uploaded, bool):
                    uploaded = {'ok': uploaded, 'raw_type': 'bool'}
                if not isinstance(uploaded, dict) or not uploaded.get('ok'):
                    await self._emit('upload_result', id=rid, ok=False, error='attach-verify')
                    text += '\nThe attachment ' + attachment['name'] + ' could not be verified. Please read the full_result_path with read_file instead.'
            await self._turn(packets[0], text, attachments[-1] if attachments else None,
                             [p['id'] for p in packets])
        elif kind == 'file_upload':
            await self._ensure(platform)
            result = await self._call('upload', packet['name'], packet['mime'], packet['data_url'], timeout=35) or {}
            await self._emit('upload_result', id=packet['id'], **result)
        elif kind == 'file_fetch':
            await self._ensure(platform)
            result = await self._call('fetchFile', packet['url'], timeout=35) or {}
            await self._emit('file_data', id=packet['id'], name=packet.get('name'), **result)
        elif kind == 'list_chats':
            await self._ensure(platform)
            result = await self._call('listChats') or {}
            await self._emit('chat_list', request_id=packet['request_id'], **result)
        elif kind in ('read_chat', 'load_older'):
            await self._ensure(platform, packet.get('url'))
            if kind == 'load_older':
                await self._call('loadOlder', timeout=30)
            result = await self._call('readChat', min(200, int(packet.get('limit', 40))), timeout=20) or {}
            result.setdefault('url', packet.get('url'))
            await self._emit('chat_content', request_id=packet['request_id'], **result)

    async def _driver(self):
        import websockets
        while not self._closing.is_set():
            try:
                async with websockets.connect(f'ws://127.0.0.1:{self.bridge.port}', max_size=24*1024*1024) as ws:
                    self._ws = ws
                    await ws.send(json.dumps({'type': 'hello', 'agent': 'internal-browser',
                                              'version': VERSION, 'token': self.bridge.token}))
                    hello = json.loads(await ws.recv())
                    if hello.get('type') != 'hello' or hello.get('version') != VERSION:
                        raise RuntimeError('Driver handshake rejected')
                    self.sink({'type': 'browser_status', 'connected': True, 'status': 'connected',
                               'driver': 'internal-browser'})
                    commands = asyncio.Queue(maxsize=100)
                    batches = {}
                    async def flush(rid):
                        await asyncio.sleep(0.7)
                        items = batches.pop(rid, [])
                        if items and not self.stopped(rid):
                            await commands.put({'type': 'tool_batch', 'items': items})
                    async def consume():
                        while True:
                            packet = await commands.get()
                            try:
                                await self._handle(packet)
                            except Exception as exc:
                                log.exception('Driver command failed')
                                await self._emit('error', error=str(exc), source='driver')
                    worker, watcher = asyncio.create_task(consume()), asyncio.create_task(self._watch())
                    flushers = set()
                    try:
                        async for raw in ws:
                            packet = json.loads(raw)
                            rid = packet.get('request_id', '')
                            if packet.get('type') == 'stop_generation':
                                self.stop_request(rid)
                                batches.pop(rid, None)
                            elif packet.get('type') == 'approval_required':
                                asyncio.create_task(self._call('approval', packet, timeout=6))
                            elif packet.get('type') == 'approval_closed':
                                asyncio.create_task(self._call('approvalDismiss', packet['id'], packet.get('approved', False), timeout=6))
                            elif packet.get('type') == 'tool_result':
                                if rid not in batches:
                                    batches[rid] = []
                                    task = asyncio.create_task(flush(rid))
                                    flushers.add(task)
                                    task.add_done_callback(flushers.discard)
                                batches[rid].append(packet)
                            else:
                                await commands.put(packet)
                    finally:
                        worker.cancel()
                        watcher.cancel()
                        for task in flushers:
                            task.cancel()
                        await asyncio.gather(worker, watcher, *flushers, return_exceptions=True)
            except Exception as exc:
                log.debug('Driver reconnect: %s', exc)
                self.sink({'type': 'browser_status', 'connected': False, 'status': 'disconnected',
                           'driver': 'internal-browser', 'detail': str(exc)})
                await asyncio.sleep(1)
            finally:
                self._ws = None
