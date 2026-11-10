import json
import threading
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
