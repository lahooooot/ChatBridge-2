import asyncio
import time
import pytest
from desktop.internal_browser import InternalBrowser, same_conversation


class Bridge:
    port = 8787
    token = 'fake'


def make_driver(snaps):
    driver = InternalBrowser(Bridge(), lambda e: None)
    emitted = []
    async def call(method, *args, **kwargs):
        return snaps.pop(0) if len(snaps) > 1 else snaps[0]
    async def emit(kind, **kwargs):
        emitted.append({'type':kind, **kwargs})
    driver._call, driver._emit = call, emit
    return driver, emitted


@pytest.mark.asyncio
async def test_optimistic_count_unchanged_text_moves():
    driver, events = make_driver([{'count':1,'text':'New answer','busy':False,'url':'https://chatgpt.com/c/1'}])
    result = await driver._capture('chatgpt','r',{'count':1,'text':'Old answer'},2)
    assert result['text'] == 'New answer'
    assert any(x['type']=='assistant_stream' for x in events)
    assert any(x['type']=='assistant_waiting' for x in events)


@pytest.mark.asyncio
async def test_stale_does_not_finish_as_new_response():
    driver, _ = make_driver([{'count':1,'text':'Old answer','busy':False}])
    result = await driver._capture('chatgpt','r',{'count':1,'text':'Old answer'},.3)
    assert result == {'failure':'stale'}


@pytest.mark.asyncio
async def test_stop_is_request_scoped():
    driver, _ = make_driver([{'count':2,'text':'New answer','busy':False}])
    driver._stopped['r'] = time.monotonic()+300
    assert await driver._capture('chatgpt','r',{'count':1,'text':'Old'},1) is None
    assert not driver.stopped('next')
    driver._stopped['r'] = time.monotonic()-1
    assert not driver.stopped('r')


@pytest.mark.asyncio
async def test_busy_blocks_stable_resolve_until_timeout():
    driver, _ = make_driver([{'count':2,'text':'Writing','busy':True}])
    start = time.monotonic()
    result = await driver._capture('chatgpt','r',{'count':1,'text':'Old'},.5)
    assert time.monotonic()-start >= .5
    assert result['text'] == 'Writing'


def test_stale_eval_lock_recovers_after_hung_native_call():
    """A hung evaluate_js must not wedge the browser forever.

    Regression for: after one message, every later evaluate() raised
    'Previous WebView script is still blocked', so model switches and
    sidebar clicks silently did nothing.
    """
    driver = InternalBrowser(Bridge(), lambda e: None)
    # Simulate an orphaned worker that acquired the lock and never returned.
    assert driver._eval_lock.acquire(timeout=1)
    start = time.monotonic()
    try:
        driver.evaluate('1+1', timeout=1)
    except Exception:
        pass
    # The stale lock must be broken and the wait must stay bounded.
    assert time.monotonic() - start < 8
    assert driver._eval_lock.acquire(timeout=1)
    driver._eval_lock.release()


def test_same_conversation():
    assert same_conversation('https://chatgpt.com/c/123/', 'https://chatgpt.com/c/123')
    assert not same_conversation('https://claude.ai/chat/123','https://chatgpt.com/c/123')
