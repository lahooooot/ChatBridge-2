import time
from desktop.app import Api, decode_data, data_url


def test_bootstrap_without_native_dependencies(tmp_path):
    api = Api(tmp_path/'data')
    boot = api.bootstrap()
    assert boot['ok'] and boot['version'] == '2.60.0'
    assert len(boot['platforms']) == 5
    assert not boot['status']['connected']
    assert boot['config']['full_access']


def test_editor_security_and_async_save(tmp_path):
    root = tmp_path/'project'
    root.mkdir()
    (root/'hello.txt').write_text('hello')
    api = Api(tmp_path/'data')
    assert api.project_attach(str(root))['ok']
    assert api.fs_read('hello.txt')['content'] == 'hello'
    assert not api.fs_read('../outside.txt')['ok']
    assert api.fs_write('hello.txt','changed')['ok']
    deadline = time.monotonic()+3
    while time.monotonic()<deadline and (root/'hello.txt').read_text()!='changed':
        time.sleep(.03)
    assert (root/'hello.txt').read_text()=='changed'
    assert any(e['type']=='fs_saved' and e['ok'] for e in api.drain_events()['events'])


def test_assistant_sanitized_before_ui(tmp_path):
    api = Api(tmp_path/'data')
    api.requests['r'] = {'chat_id':'owner','workspace':None,'stopped':False}
    raw = 'I will read it.\n```chatbridge-tool-call\n{"tool":"read_file","args":{"path":"a.py"}}\n```'
    api._event({'type':'assistant_response','request_id':'r','text':raw,'page_url':'https://chatgpt.com/c/123'})
    event = api.drain_events()['events'][0]
    assert 'chatbridge-tool-call' not in event['text']
    assert event['operations'][0]['verb']=='read'
    assert event['chat_id']=='owner'
    assert api.chat_urls['owner'].endswith('/123')


def test_remote_approval_cannot_authorize_local_execution(tmp_path):
    import threading
    api = Api(tmp_path/'data')
    event = threading.Event()
    api.approvals['t']={'event':event,'approved':False}
    api._event({'type':'approval_response','id':'t','approved':True})
    assert not event.is_set() and not api.approvals['t']['approved']
    assert api.approval_response('t', True)['ok']
    assert event.is_set() and api.approvals['t']['approved']


def test_provider_turn_never_executes_tools(tmp_path):
    api = Api(tmp_path/'data')
    api._event({'type':'tool_call','request_id':'prov-r','id':'t','tool':'write_file','args':{'path':'x','content':'bad'}})
    assert not api.seen_tools


def test_tool_execute_round_trip_and_stop(tmp_path):
    root = tmp_path/'workspace'
    root.mkdir()
    (root/'file.txt').write_text('actual content')
    api = Api(tmp_path/'data')
    packets = []
    api.bridge.send = packets.append
    api.requests['r']={'chat_id':'c','workspace':str(root),'stopped':False}
    call = {'id':'t','request_id':'r','tool':'read_file','args':{'path':'file.txt'},'platform':'chatgpt'}
    api._execute_tool(call)
    assert packets[-1]['type']=='tool_result'
    assert packets[-1]['result']['content']=='actual content'
    api.requests['r']['stopped']=True
    count = len(packets)
    api._execute_tool({**call,'id':'t2'})
    assert len(packets)==count


def test_data_url_validation():
    value = data_url('example.text',b'example')
    assert value.startswith('data:text/plain;')
    assert decode_data(value)==b'example'


def test_workspace_switch_and_conversation_restore(tmp_path):
    first=tmp_path/'first'; second=tmp_path/'second'
    first.mkdir(); second.mkdir()
    api=Api(tmp_path/'data')
    assert api.project_attach(str(first))['ok']
    state={'project_path':str(second),'chats':[{'id':'c','url':'https://chatgpt.com/c/old'}]}
    assert api.state_save(state)['ok']
    assert api.project['path']==str(second.resolve())
    restored=Api(tmp_path/'data')
    assert restored.chat_urls['c']=='https://chatgpt.com/c/old'
    assert restored.project['path']==str(second.resolve())
    assert restored.state_save({'project_path':None})['ok']
    assert restored.project is None


def test_model_switch_transfers_context_not_old_site_url(tmp_path):
    api=Api(tmp_path/'data')
    api._browser.open=lambda platform: None
    packets=[]
    api.bridge.send=packets.append
    api.last_platforms['c']='chatgpt'
    api.state_save({'project_path':None,'chats':[{'id':'c','platform':'claude','url':'https://chatgpt.com/c/123','messages':[{'role':'assistant','text':'Previous plan'}]}]})
    result=api.send_message('Continue','claude','c')
    assert result['ok']
    deadline=time.monotonic()+3
    while not packets and time.monotonic()<deadline:
        time.sleep(.01)
    assert packets[0]['platform']=='claude'
    assert packets[0]['conv_url'] is None
    assert 'Previous plan' in packets[0]['text']


def test_pywebview_native_window_is_not_public_js_api_field(tmp_path):
    api = Api(tmp_path/'data')
    assert 'window' not in api.__dict__
    assert api.__dict__.get('_window') is None


def test_pywebview_api_keeps_native_browser_private(tmp_path):
    api = Api(tmp_path/'data')
    assert 'browser' not in api.__dict__
    assert api.__dict__.get('_browser') is not None
