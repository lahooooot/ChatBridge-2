import json
import re
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from desktop.app import Api
from desktop.provider_models import (BUILTIN_PLATFORM_NAMES, build_models, default_models,
                                    model_id_for, platform_for_model)
from desktop.provider_presets import (KEY_ENV, build_snippet, hermes_config_path,
                                      list_presets, opencode_config_path)
from desktop.provider_server import ProviderServer

ROOT = Path(__file__).resolve().parents[1]


class FakeBridge:
    connected = True

    def __init__(self):
        self.owner = None
        self.packets = []

    def send(self, packet):
        self.packets.append(packet)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def request(server, path='/v1/models', body=None, key='test-key'):
    req = urllib.request.Request(f'http://127.0.0.1:{server.port}' + path,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Authorization': 'Bearer ' + key,
                                          'Content-Type': 'application/json'})
    return urllib.request.urlopen(req, timeout=4)


def test_model_registry_follows_the_configured_platforms():
    models = build_models([{'id': 'chatgpt', 'name': 'ChatGPT', 'home': 'https://chatgpt.com'}],
                          [{'id': 'c_demo', 'name': 'Demo', 'home': 'https://example.com'}])
    assert [row['id'] for row in models] == ['web-chatgpt', 'web-c_demo']
    assert models[1]['platform'] == 'c_demo'
    assert models[1]['name'] == 'Demo'
    assert platform_for_model('web-c_demo') == 'c_demo'
    assert model_id_for('gemini') == 'web-gemini'
    assert len(default_models()) == len(BUILTIN_PLATFORM_NAMES)


def test_custom_models_are_exposed_by_the_server():
    bridge = FakeBridge()
    server = ProviderServer(bridge, 'test-key', port=0, timeout=1,
                             models=build_models([{'id': 'chatgpt', 'name': 'ChatGPT'}],
                                                 [{'id': 'c_demo', 'name': 'Demo'}])).start()
    bridge.owner = server
    try:
        data = json.load(request(server))['data']
        assert [row['id'] for row in data] == ['web-chatgpt', 'web-c_demo']
        assert data[0]['name'] == 'ChatGPT'
        assert json.load(request(server, '/v1/models/web-c_demo'))['id'] == 'web-c_demo'
        with pytest.raises(urllib.error.HTTPError) as exc:
            request(server, '/v1/models/web-nope')
        assert exc.value.code == 404
    finally:
        server.stop()


def test_a_custom_model_posts_to_its_own_platform():
    bridge = FakeBridge()
    server = ProviderServer(bridge, 'test-key', port=0, timeout=1,
                             models=build_models([], [{'id': 'c_demo', 'name': 'Demo'}])).start()
    bridge.owner = server
    try:
        with pytest.raises(Exception):
            request(server, '/v1/chat/completions',
                    {'model': 'web-c_demo', 'messages': [{'role': 'user', 'content': 'x'}]})
    finally:
        server.stop()
    assert bridge.packets[0]['platform'] == 'c_demo'
    assert bridge.packets[0]['request_id'].startswith('prov-')


def test_opencode_preset_matches_the_real_config_shape():
    models = build_models([{'id': 'chatgpt', 'name': 'ChatGPT'}])
    snippet = build_snippet('opencode', 'http://127.0.0.1:8788/v1', 'secret', models)
    payload = json.loads(snippet)
    provider = payload['provider']['chatbridge']
    assert provider['npm'] == '@ai-sdk/openai-compatible'
    assert provider['options']['baseURL'] == 'http://127.0.0.1:8788/v1'
    assert provider['options']['apiKey'] == 'secret'
    assert provider['models']['web-chatgpt']['name'] == 'ChatGPT'
    assert payload['model'] == 'chatbridge/web-chatgpt'


def test_hermes_preset_follows_config_yaml_and_the_env_file():
    models = build_models([{'id': 'chatgpt', 'name': 'ChatGPT'},
                           {'id': 'c_demo', 'name': 'Demo'}])
    snippet = build_snippet('hermes', 'http://127.0.0.1:8788/v1', 'secret', models)
    assert 'providers:' in snippet
    assert '  chatbridge:' in snippet
    assert '    base_url: http://127.0.0.1:8788/v1' in snippet
    assert '    discover_models: true' in snippet
    assert '      web-chatgpt: {}' in snippet
    assert '      web-c_demo: {}' in snippet
    assert '    key_env: ' + KEY_ENV in snippet
    assert KEY_ENV + '=secret' in snippet


def test_generic_presets_cover_any_other_agent():
    models = build_models([{'id': 'chatgpt', 'name': 'ChatGPT'}])
    env = build_snippet('generic-env', 'http://127.0.0.1:8788/v1', 'secret', models)
    assert 'OPENAI_BASE_URL=http://127.0.0.1:8788/v1' in env
    assert 'OPENAI_API_KEY=secret' in env
    yaml_text = build_snippet('generic-yaml', 'http://127.0.0.1:8788/v1', 'secret', models)
    assert '    base_url: http://127.0.0.1:8788/v1' in yaml_text
    assert '      web-chatgpt: {}' in yaml_text
    curl = build_snippet('curl', 'http://127.0.0.1:8788/v1', 'secret', models)
    assert curl.startswith('curl http://127.0.0.1:8788/v1/chat/completions')
    assert 'web-chatgpt' in curl


def test_preset_registry_is_extensible_and_reports_config_paths():
    presets = list_presets('http://127.0.0.1:8788/v1', 'secret',
                           build_models([{'id': 'chatgpt', 'name': 'ChatGPT'}]))
    ids = {row['id'] for row in presets}
    assert {'opencode', 'hermes', 'generic-json', 'generic-yaml', 'generic-env', 'curl'} <= ids
    assert all(row['snippet'] for row in presets)
    opencode = next(row for row in presets if row['id'] == 'opencode')
    assert opencode['config_path'] == str(opencode_config_path())
    assert opencode['config_path'].endswith('opencode.json')
    hermes = next(row for row in presets if row['id'] == 'hermes')
    assert hermes['config_path'] == str(hermes_config_path())
    assert hermes['config_path'].endswith('config.yaml')
    with pytest.raises(ValueError):
        build_snippet('nope', 'http://127.0.0.1:8788/v1', 'secret', [])


def test_desktop_api_exposes_provider_models_and_presets(tmp_path):
    api = Api(tmp_path / 'data')
    api.config.update({'custom_models': [{'id': 'c_demo', 'name': 'Demo',
                                          'home': 'https://example.com'}]})
    result = api.provider_models()
    assert result['ok']
    assert result['base_url'].startswith('http://127.0.0.1:')
    ids = [row['id'] for row in result['models']]
    assert 'web-chatgpt' in ids and 'web-c_demo' in ids
    assert {row['id'] for row in result['presets']} >= {'opencode', 'hermes', 'generic-json'}
    assert all(row['snippet'] for row in result['presets'])


def test_provider_test_and_key_rotation(tmp_path):
    api = Api(tmp_path / 'data')
    port = free_port()
    api.config.update({'provider_port': port})
    api.provider_set(True, port)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not api.provider:
        time.sleep(0.02)
    try:
        assert api.provider is not None
        result = api.provider_test()
        assert result['ok'] and 'web-chatgpt' in result['models']
        old_key = api.config.get()['provider_key']
        rotated = api.provider_key_rotate()
        assert rotated['key'] != old_key
        assert api.config.get()['provider_key'] == rotated['key']
        assert api.provider_test()['ok']
    finally:
        if api.provider:
            api.provider.stop()


def test_provider_settings_markup_and_bindings_exist():
    html = (ROOT / 'desktop' / 'ui' / 'index.html').read_text(encoding='utf-8')
    js = (ROOT / 'desktop' / 'ui' / 'app.js').read_text(encoding='utf-8')
    for element_id in ('providerSwitch', 'providerPort', 'providerTimeout', 'providerKey',
                       'providerEndpoint', 'providerBaseUrl', 'providerModels',
                       'providerRefreshBtn', 'providerCopyUrlBtn', 'providerRevealBtn',
                       'providerCopyKeyBtn', 'providerRotateBtn', 'providerState',
                       'providerTestBtn', 'providerPresetTabs', 'providerPresetNote',
                       'providerSnippet', 'providerCopySnippetBtn'):
        assert 'id="' + element_id + '"' in html
    for method in ('provider_models', 'provider_test', 'provider_key_rotate'):
        assert "'" + method + "'" in js
    assert 'innerHTML' not in js


def test_every_ui_translation_key_exists_in_both_catalogs():
    html = (ROOT / 'desktop' / 'ui' / 'index.html').read_text(encoding='utf-8')
    catalogs = {locale: json.loads((ROOT / 'desktop' / 'translations' / f'{locale}.json').read_text(encoding='utf-8'))
                for locale in ('en', 'fa')}
    keys = set(re.findall(r'data-i18n(?:-placeholder)?="([^"]+)"', html))
    assert keys
    for locale, catalog in catalogs.items():
        assert not keys - catalog.keys(), locale + ': missing translations'
    assert catalogs['en'].keys() == catalogs['fa'].keys()
    for key in ('provider_reveal', 'provider_hide', 'provider_copy_key', 'provider_copy_url',
                'provider_rotate', 'provider_rotate_title', 'provider_rotate_confirm',
                'provider_key_rotated', 'provider_base_url', 'provider_models',
                'provider_no_models', 'provider_refresh', 'provider_state', 'provider_running',
                'provider_stopped', 'provider_test', 'provider_test_ok', 'provider_test_failed',
                'provider_connect_agent', 'provider_copy_snippet', 'provider_copied',
                'provider_copy_failed'):
        assert key in catalogs['en'] and key in catalogs['fa']
