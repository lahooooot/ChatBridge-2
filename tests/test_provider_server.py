import json
import threading
import time
import urllib.request
import urllib.error
import pytest
from desktop.provider_server import ProviderServer, flatten_messages


class FakeBridge:
    connected = True
    def __init__(self):
        self.owner = None
        self.packets = []
        self.answer = 'Hello from the web'
    def send(self, packet):
        self.packets.append(packet)
        if packet['type'] == 'user_message':
            rid = packet['request_id']
            def answer():
                self.owner.on_event({'type': 'assistant_stream', 'request_id': rid, 'text': self.answer})
                self.owner.on_event({'type': 'assistant_response', 'request_id': rid, 'text': self.answer})
            threading.Thread(target=answer, daemon=True).start()


@pytest.fixture
def provider():
    bridge = FakeBridge()
    server = ProviderServer(bridge, 'test-key', port=0, timeout=1).start()
    bridge.owner = server
    yield server, bridge
    server.stop()


def request(server, path='/v1/models', body=None, key='test-key'):
    req = urllib.request.Request(f'http://127.0.0.1:{server.port}' + path,
          data=json.dumps(body).encode() if body is not None else None,
          headers={'Authorization': 'Bearer '+key, 'Content-Type': 'application/json'})
    return urllib.request.urlopen(req, timeout=4)


def test_models_auth(provider):
    server, _ = provider
    assert len(json.load(request(server))['data']) == 5
    with pytest.raises(urllib.error.HTTPError) as exc:
        request(server, key='wrong')
    assert exc.value.code == 401


def test_dynamic_models_and_single_model_endpoint():
    bridge = FakeBridge()
    models = [{'id': 'web-custom:reasoner', 'name': 'Reasoner', 'platform': 'custom:reasoner'}]
    server = ProviderServer(bridge, 'test-key', port=0, timeout=1, models=models).start()
    bridge.owner = server
    try:
        listed = json.load(request(server))['data']
        assert [item['id'] for item in listed] == ['web-custom:reasoner']
        detail = json.load(request(server, '/v1/models/web-custom:reasoner'))
        assert detail['id'] == 'web-custom:reasoner'
        assert detail['name'] == 'Reasoner'
        assert server.platform_for('web-custom:reasoner') == 'custom:reasoner'
        with pytest.raises(urllib.error.HTTPError) as exc:
            request(server, '/v1/models/web-unknown')
        assert exc.value.code == 404
    finally:
        server.stop()


def test_completion(provider):
    server, bridge = provider
    value = json.load(request(server, '/v1/chat/completions', {'model':'web-chatgpt','messages':[{'role':'user','content':'Hello'}]}))
    assert value['choices'][0]['message']['content'] == bridge.answer
    assert bridge.packets[0]['request_id'].startswith('prov-')
    assert bridge.packets[0]['fresh'] is True
    assert value['chatbridge']['usage_is_unavailable']


def test_native_tool_calls_not_executed(provider):
    server, bridge = provider
    bridge.answer = 'I will inspect it.\n```chatbridge-tool-call\n{"tool":"read_file","args":{"path":"x.py"}}\n```'
    value = json.load(request(server, '/v1/chat/completions', {'model':'web-claude','messages':[{'role':'user','content':'Read'}]}))
    choice = value['choices'][0]
    assert choice['finish_reason'] == 'tool_calls'
    assert choice['message']['tool_calls'][0]['function']['name'] == 'read_file'
    assert 'chatbridge-tool-call' not in choice['message']['content']
    assert all(p['type'] != 'tool_result' for p in bridge.packets)


def test_stream(provider):
    server, _ = provider
    text = request(server, '/v1/chat/completions', {'messages':[{'role':'user','content':'Hi'}],'stream':True}).read().decode()
    assert 'chat.completion.chunk' in text and 'data: [DONE]' in text
    assert 'Hello from the web' in text


def test_validation_and_offline(provider):
    server, bridge = provider
    with pytest.raises(urllib.error.HTTPError) as exc:
        request(server, '/v1/chat/completions', {'messages':[]})
    assert exc.value.code == 400
    bridge.connected = False
    with pytest.raises(urllib.error.HTTPError) as exc:
        request(server, '/v1/chat/completions', {'messages':[{'role':'user','content':'x'}]})
    assert exc.value.code == 503


def test_flatten_tool_messages():
    assert 'result' in flatten_messages([{'role':'tool','content':'result'}])


def test_model_names_accept_the_provider_prefix_and_any_case(provider):
    # Real clients ask for "chatbridge/web-chatgpt" (the id the opencode
    # snippet advertises) while others send the bare id or a different case.
    # All three must reach the same web platform instead of a 400.
    server, bridge = provider
    for model_name in ('web-chatgpt', 'chatbridge/web-chatgpt', 'WEB-ChatGPT'):
        value = json.load(request(server, '/v1/chat/completions',
                                  {'model': model_name,
                                   'messages': [{'role': 'user', 'content': 'Hi'}]}))
        assert value['choices'][0]['message']['content'] == bridge.answer
        assert bridge.packets[-1]['platform'] == 'chatgpt'


def test_a_request_opens_the_browser_when_the_driver_is_missing():
    bridge = FakeBridge()
    bridge.connected = False
    opened = []

    def ensure_browser(platform):
        opened.append(platform)
        bridge.connected = True

    server = ProviderServer(bridge, 'test-key', port=0, timeout=5,
                            ensure_browser=ensure_browser, connect_wait=2).start()
    bridge.owner = server
    try:
        value = json.load(request(server, '/v1/chat/completions',
                                  {'model': 'web-chatgpt',
                                   'messages': [{'role': 'user', 'content': 'Hi'}]}))
        assert value['choices'][0]['message']['content'] == bridge.answer
        assert opened == ['chatgpt']
        assert bridge.packets[0]['type'] == 'user_message'
    finally:
        server.stop()


def test_a_browser_that_never_connects_fails_fast_with_503():
    bridge = FakeBridge()
    bridge.connected = False
    server = ProviderServer(bridge, 'test-key', port=0, timeout=5,
                            ensure_browser=lambda platform: None, connect_wait=0.2).start()
    bridge.owner = server
    started = time.monotonic()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            request(server, '/v1/chat/completions',
                    {'messages': [{'role': 'user', 'content': 'Hi'}]})
        assert exc.value.code == 503
        assert time.monotonic() - started < 5
        assert 'internal browser' in server.status()['last_error'].lower()
    finally:
        server.stop()


def test_health_and_status_expose_the_live_state(provider):
    server, _bridge = provider
    with urllib.request.urlopen(f'http://127.0.0.1:{server.port}/health', timeout=4) as response:
        health = json.load(response)
    assert health['ok'] is True
    assert health['running'] is True
    assert 'web-chatgpt' in health['models']
    snapshot = server.status()
    assert snapshot['running'] is True
    assert snapshot['served'] == 0
    assert snapshot['models'] == [entry['id'] for entry in server.models]
    with pytest.raises(urllib.error.HTTPError) as exc:
        request(server, '/v1/chat/completions',
                {'model': 'web-nope', 'messages': [{'role': 'user', 'content': 'Hi'}]})
    assert exc.value.code == 400
    assert 'web-nope' in server.status()['last_error']
    assert server.status()['last_request']['ok'] is False


def test_status_counts_successful_turns(provider):
    server, _bridge = provider
    json.load(request(server, '/v1/chat/completions',
                      {'model': 'web-chatgpt', 'messages': [{'role': 'user', 'content': 'Hi'}]}))
    assert server.status()['served'] == 1
    assert server.status()['last_request']['ok'] is True
