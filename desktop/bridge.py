"""Authenticated loopback WebSocket transport. UI never waits for the driver."""
from __future__ import annotations
import asyncio
import json
import logging
import queue
import secrets
import threading
from collections import deque

log = logging.getLogger(__name__)
VERSION = '2.60.0'


class UISink:
    def __init__(self, capacity=4000):
        self._queue = queue.Queue(maxsize=capacity)

    def __call__(self, event):
        try:
            self._queue.put_nowait(dict(event))
        except queue.Full:
            # Prefer a bounded UI queue to unbounded memory use.
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(dict(event))
            except queue.Empty:
                pass

    def drain(self, limit=250):
        result = []
        for _ in range(limit):
            try:
                result.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return result


class Bridge:
    def __init__(self, port=8787, sink=None, on_event=None, token=None):
        self.port = int(port)
        self.sink = sink or UISink()
        self.on_event = on_event
        self.token = token or secrets.token_urlsafe(32)
        self.loop = None
        self.client = None
        self.ready_platform = None
        self.pending = deque(maxlen=100)
        self.started = threading.Event()
        self.error = None
        self.server = None
        self._thread = None

    @property
    def connected(self):
        return self.client is not None and not self.client.closed

    def emit(self, event):
        if self.on_event:
            try:
                self.on_event(event)
            except Exception:
                log.exception('Bridge event handler failed')
        else:
            self.sink(event)

    async def handler(self, ws, path=None):
        owned = False
        try:
            packet = json.loads(await asyncio.wait_for(ws.recv(), 5))
            if packet.get('type') != 'hello' or not secrets.compare_digest(
                    str(packet.get('token', '')), self.token):
                await ws.close(4001, 'Driver authentication required')
                return
            if self.connected:
                await ws.close(4009, 'Internal driver slot already occupied')
                return
            if packet.get('version') != VERSION:
                await ws.close(4002, 'Protocol version mismatch')
                return
            self.client = ws
            owned = True
            self.ready_platform = None
            await ws.send(json.dumps({'type': 'hello', 'version': VERSION, 'ready': True}))
            self.emit({'type': 'browser_status', 'connected': True, 'status': 'preparing'})
            # Driver owns navigation. Deliver pending commands even before cs_ready.
            while self.pending:
                await ws.send(json.dumps(self.pending.popleft(), ensure_ascii=False))
            async for raw in ws:
                try:
                    event = json.loads(raw)
                    if not isinstance(event, dict) or not isinstance(event.get('type'), str):
                        continue
                    if event['type'] == 'cs_ready':
                        self.ready_platform = event.get('platform')
                    self.emit(event)
                except (ValueError, TypeError):
                    log.warning('Malformed driver packet discarded')
        except Exception as exc:
            log.debug('Driver disconnected: %s', exc)
        finally:
            if owned and self.client is ws:
                self.client = None
                self.ready_platform = None
                self.emit({'type': 'browser_status', 'connected': False, 'status': 'disconnected'})

    async def _send(self, packet):
        if self.connected:
            try:
                await self.client.send(json.dumps(packet, ensure_ascii=False))
                return
            except Exception:
                pass
        if len(self.pending) >= self.pending.maxlen:
            self.emit({'type': 'prompt_error', 'request_id': packet.get('request_id'),
                       'platform': packet.get('platform'), 'reason': 'no-tab'})
        else:
            self.pending.append(dict(packet))

    def send(self, packet):
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self._send(packet), self.loop)
        else:
            self.pending.append(dict(packet))

    async def _serve(self):
        import websockets
        self.server = await websockets.serve(self.handler, '127.0.0.1', self.port,
                                             max_size=24 * 1024 * 1024, ping_interval=20)
        self.port = self.server.sockets[0].getsockname()[1]
        self.started.set()
        await self.server.wait_closed()

    def start(self):
        def runner():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(self._serve())
            except Exception as exc:
                message = str(exc)
                code = getattr(exc, 'winerror', None) or getattr(exc, 'errno', None)
                lowered = message.lower()
                if (code == 10048 or 'winerror 10048' in lowered
                        or 'address already in use' in lowered
                        or 'only one usage' in lowered):
                    message = (
                        'Port ' + str(self.port) + ' is already in use. Another ChatBridge '
                        'window is probably still running. Close it (or end ChatBridge in '
                        'Task Manager) and start ChatBridge again.'
                    )
                self.error = message
                self.started.set()
                self.emit({'type': 'error', 'error': message, 'source': 'bridge'})
            finally:
                self.loop.close()
        self._thread = threading.Thread(target=runner, daemon=True, name='bridge-ws')
        self._thread.start()
        return self

    def stop(self, timeout=3):
        """Release the driver socket and the listening port, then stop the loop.

        server.close() only schedules the close. Without wait_closed() the
        listening socket can outlive the process on Windows, and the next
        launch fails to bind with WinError 10048.
        """
        if not (self.loop and self.loop.is_running()):
            return
        async def shutdown():
            try:
                if self.client:
                    await self.client.close()
            except Exception:
                log.debug('Driver socket close failed', exc_info=True)
            if self.server:
                self.server.close()
                try:
                    await asyncio.wait_for(self.server.wait_closed(), timeout=timeout)
                except Exception:
                    log.debug('Bridge server did not close in time', exc_info=True)
        try:
            future = asyncio.run_coroutine_threadsafe(shutdown(), self.loop)
            future.result(timeout=timeout)
        except Exception:
            log.debug('Bridge shutdown failed', exc_info=True)
        # Stop the loop so the socket is fully released and the thread exits.
        try:
            self.loop.call_soon_threadsafe(self.loop.stop)
        except Exception:
            log.debug('Could not stop bridge loop', exc_info=True)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
