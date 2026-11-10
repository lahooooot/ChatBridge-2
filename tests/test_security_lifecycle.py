import asyncio
import threading
import time
import pytest
from desktop.internal_browser import InternalBrowser, PLATFORM_HOME
from desktop.app import Api


class Bridge:
    port=8787
    token='test'


def test_stopping_queued_turn_does_not_stop_active_page():
    driver=InternalBrowser(Bridge(),lambda e:None)
    driver._active='active-A'
    calls=[]
    driver.evaluate=lambda *a,**kw: calls.append('stop')
    driver.stop_request('queued-B')
    time.sleep(.03)
    assert driver.stopped('queued-B')
    assert calls==[]


def test_delayed_native_stop_checks_owner_again():
    driver=InternalBrowser(Bridge(),lambda e:None)
    driver._active='active-A'
    done=threading.Event()
    calls=[]
    class Window:
        def evaluate_js(self,script,callback):
            calls.append(script); callback({'ok':True})
    driver.window=Window()
    driver._eval_lock.acquire()
    worker=threading.Thread(target=lambda:(driver._quiet_stop('active-A'),done.set()))
    worker.start()
    time.sleep(.02)
    driver._active='active-C'
    driver._eval_lock.release()
    assert done.wait(2)
    assert not calls


@pytest.mark.asyncio
async def test_fresh_provider_ensure_resets_private_conversation():
    driver=InternalBrowser(Bridge(),lambda e:None)
    loaded=[]
    driver._loaded.set()
    class Window:
        def load_url(self,url):
            loaded.append(url);driver._loaded.set()
    driver.window=Window()
    async def call(*args,**kwargs):return {'url':'https://chatgpt.com/c/private-desktop-chat'}
    async def emit(*args,**kwargs):pass
    driver._call,driver._emit=call,emit
    await driver._ensure('chatgpt',fresh=True)
    assert loaded==[PLATFORM_HOME['chatgpt']]


def test_stopped_waiting_cannot_rearm_ui(tmp_path):
    api=Api(tmp_path/'data')
    api.requests['r']={'chat_id':'c','stopped':True}
    api._event({'type':'assistant_waiting','request_id':'r','stage':'waiting'})
    assert api.drain_events()['events']==[]


def test_stop_api_uses_single_ws_dispatch(tmp_path):
    api=Api(tmp_path/'data')
    calls=[]
    api.bridge.send=calls.append
    api._browser.stop_request=lambda rid: (_ for _ in ()).throw(AssertionError('duplicate direct stop'))
    assert api.stop_message('queued-B','chatgpt')['ok']
    assert len(calls)==1 and calls[0]['type']=='stop_generation'


@pytest.mark.asyncio
async def test_cancelled_queued_turn_does_not_poison_active_owner():
    driver=InternalBrowser(Bridge(),lambda e:None)
    driver._active='active-A'
    driver._stopped['queued-B']=time.monotonic()+300
    await driver._turn({'platform':'chatgpt','request_id':'queued-B'},'do not send')
    assert driver._active=='active-A'
