import threading
import pytest
from desktop.internal_browser import InternalBrowser


class Bridge:
    port=8787
    token='test'


@pytest.mark.asyncio
async def test_turn_parses_once_and_dispatches_stable_ids():
    driver=InternalBrowser(Bridge(),lambda e:None)
    emitted=[]
    methods=[]
    async def ensure(*args): pass
    async def idle(*args): return True
    async def call(method,*args,**kwargs):
        methods.append(method)
        if method == 'waitReady': return {'ok':True,'ready':True,'editor':True,'send':True}
        if method=='send': return {'ok':True,'verdict':'accepted'}
        return {'count':1,'text':'old','url':'https://chatgpt.com/c/x'}
    async def capture(*args):
        return {'count':2,'text':'Done.\n```chatbridge-tool-call\n{"tool":"list_dir","args":{"path":"."}}\n```','url':'https://chatgpt.com/c/x'}
    async def emit(kind,**kwargs): emitted.append({'type':kind,**kwargs})
    driver._ensure,driver._wait_idle,driver._call,driver._capture,driver._emit=ensure,idle,call,capture,emit
    await driver._turn({'platform':'chatgpt','request_id':'r'},'hello')
    response=next(e for e in emitted if e['type']=='assistant_response')
    call=next(e for e in emitted if e['type']=='tool_call')
    assert response['parsed_calls'][0]['id']==call['id']
    assert methods.index('baseline')<methods.index('send')


@pytest.mark.asyncio
async def test_turn_normalizes_boolean_webview_send_result():
    driver=InternalBrowser(Bridge(),lambda e:None)
    emitted=[]
    async def ensure(*args): pass
    async def idle(*args): return True
    async def call(method,*args,**kwargs):
        if method == 'waitReady': return {'ok':True,'ready':True,'editor':True}
        if method == 'send': return True
        return {'count':1,'text':'old','url':'https://chatgpt.com/c/x'}
    async def capture(*args): return {'count':2,'text':'Done','url':'https://chatgpt.com/c/x'}
    async def emit(kind,**kwargs): emitted.append({'type':kind,**kwargs})
    driver._ensure,driver._wait_idle,driver._call,driver._capture,driver._emit=ensure,idle,call,capture,emit
    await driver._turn({'platform':'chatgpt','request_id':'bool-send'},'hello')
    assert any(e['type']=='assistant_response' and e['text']=='Done' for e in emitted)


@pytest.mark.asyncio
async def test_turn_normalizes_boolean_upload_result():
    driver=InternalBrowser(Bridge(),lambda e:None)
    emitted=[]
    async def ensure(*args): pass
    async def idle(*args): return True
    async def call(method,*args,**kwargs):
        if method == 'waitReady': return {'ok':True,'ready':True,'editor':True}
        if method in ('upload','send'): return True
        return {'count':1,'text':'old','url':'https://chatgpt.com/c/x'}
    async def capture(*args): return {'count':2,'text':'Done','url':'https://chatgpt.com/c/x'}
    async def emit(kind,**kwargs): emitted.append({'type':kind,**kwargs})
    driver._ensure,driver._wait_idle,driver._call,driver._capture,driver._emit=ensure,idle,call,capture,emit
    attachment={'name':'result.txt','mime':'text/plain','data_url':'data:text/plain;base64,ZA=='}
    await driver._turn({'platform':'chatgpt','request_id':'bool-upload'},'hello',attachment=attachment)
    assert any(e['type']=='assistant_response' and e['text']=='Done' for e in emitted)


@pytest.mark.asyncio
async def test_provider_turn_skips_local_dispatch():
    driver=InternalBrowser(Bridge(),lambda e:None)
    emitted=[]
    async def ensure(*args): pass
    async def idle(*args): return True
    async def call(method,*args,**kwargs): return {'ok':True,'verdict':'accepted','text':'old','count':1}
    async def capture(*args): return {'text':'```chatbridge-tool-call\n{"tool":"run_command","args":{"cmd":"bad"}}\n```'}
    async def emit(kind,**kwargs): emitted.append({'type':kind,**kwargs})
    driver._ensure,driver._wait_idle,driver._call,driver._capture,driver._emit=ensure,idle,call,capture,emit
    await driver._turn({'platform':'chatgpt','request_id':'prov-1'},'hello')
    assert not any(e['type']=='tool_call' for e in emitted)


@pytest.mark.asyncio
async def test_transcript_url_is_not_duplicate_keyword():
    driver=InternalBrowser(Bridge(),lambda e:None)
    emitted=[]
    async def ensure(*args): pass
    async def call(*args,**kwargs): return {'ok':True,'url':'https://chatgpt.com/c/x','messages':[{'role':'user','text':'hi'}]}
    async def emit(kind,**kwargs): emitted.append({'type':kind,**kwargs})
    driver._ensure,driver._call,driver._emit=ensure,call,emit
    await driver._handle({'type':'read_chat','platform':'chatgpt','request_id':'r','url':'https://chatgpt.com/c/x'})
    assert emitted[0]['type']=='chat_content' and emitted[0]['ok']


def test_evaluate_waits_for_promise_callback():
    driver=InternalBrowser(Bridge(),lambda e:None)
    class Window:
        def evaluate_js(self,script,callback):
            threading.Timer(.02,lambda:callback({'ok':True})).start()
            return None
    driver.window=Window()
    assert driver.evaluate('promise',timeout=1)=={'ok':True}


def test_deepseek_hint_accepts_current_contenteditable_composer():
    source = open('desktop/agent_cb.js', encoding='utf-8').read()
    assert 'div[contenteditable="true"]' in source
    assert 'waitReady' in source
    assert 'if (last.editor) return {...last, ready: true};' in source
