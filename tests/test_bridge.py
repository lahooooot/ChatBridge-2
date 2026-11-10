import asyncio
import json
import pytest
import websockets
from desktop.bridge import Bridge, UISink


@pytest.fixture
def bridge():
    bridge = Bridge(port=0).start()
    assert bridge.started.wait(5)
    assert bridge.error is None
    yield bridge
    bridge.stop()


async def hello(ws, bridge, token=None):
    await ws.send(json.dumps({'type': 'hello', 'version': '2.50.0', 'agent': 'internal-browser',
                              'token': token if token is not None else bridge.token}))
    return json.loads(await ws.recv())


@pytest.mark.asyncio
async def test_single_client_and_reclaim(bridge):
    url = f'ws://127.0.0.1:{bridge.port}'
    async with websockets.connect(url) as first:
        assert (await hello(first, bridge))['ready']
        async with websockets.connect(url) as second:
            await second.send(json.dumps({'type': 'hello', 'version': '2.50.0', 'agent': 'internal-browser', 'token': bridge.token}))
            with pytest.raises(websockets.ConnectionClosed) as exc:
                await second.recv()
            assert exc.value.rcvd.code == 4009
    await asyncio.sleep(.1)
    async with websockets.connect(url) as third:
        assert (await hello(third, bridge))['ready']


@pytest.mark.asyncio
async def test_pending_and_ui_events(bridge):
    bridge.send({'type': 'user_message', 'text': 'queued', 'request_id': '1', 'platform': 'claude'})
    await asyncio.sleep(.05)
    async with websockets.connect(f'ws://127.0.0.1:{bridge.port}') as ws:
        await hello(ws, bridge)
        assert json.loads(await ws.recv())['text'] == 'queued'
        await ws.send(json.dumps({'type': 'cs_ready', 'platform': 'claude', 'page_url': 'https://claude.ai/chat/1'}))
        await asyncio.sleep(.05)
        assert bridge.ready_platform == 'claude'
        assert any(e['type'] == 'cs_ready' for e in bridge.sink.drain())


@pytest.mark.asyncio
async def test_auth_required(bridge):
    async with websockets.connect(f'ws://127.0.0.1:{bridge.port}') as ws:
        with pytest.raises(websockets.ConnectionClosed) as exc:
            await hello(ws, bridge, 'wrong')
        assert exc.value.rcvd.code == 4001


def test_sink_bounded_and_drains():
    sink = UISink(2)
    for i in range(5):
        sink({'type': 'test', 'i': i})
    assert [e['i'] for e in sink.drain()] == [3, 4]
    assert sink.drain() == []
