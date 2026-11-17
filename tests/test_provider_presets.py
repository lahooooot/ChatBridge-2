import json

import pytest

from desktop.provider_models import build_models, model_id_for, platform_for_model
from desktop.provider_presets import build_opencode, build_hermes, list_presets


MODELS = [
    {'id': 'chatgpt', 'name': 'ChatGPT'},
    {'id': 'custom:reasoner', 'name': 'Custom Reasoner'},
]
BASE_URL = 'http://127.0.0.1:8788/v1'
API_KEY = 'test-secret'


def test_model_registry_keeps_explicit_custom_platform_mapping():
    models = build_models([{'id': 'chatgpt', 'name': 'ChatGPT'}],
                          [{'id': 'custom:reasoner', 'name': 'Reasoner'}])
    assert models == [
        {'id': 'web-chatgpt', 'name': 'ChatGPT', 'platform': 'chatgpt'},
        {'id': 'web-custom:reasoner', 'name': 'Reasoner', 'platform': 'custom:reasoner'},
    ]
    assert model_id_for('custom:reasoner') == 'web-custom:reasoner'
    assert platform_for_model('web-custom:reasoner') == 'custom:reasoner'


def test_model_registry_skips_invalid_and_duplicate_platform_rows():
    models = build_models(
        [{'id': 'chatgpt', 'name': 'ChatGPT'}, {'id': 'chatgpt', 'name': 'Duplicate'}, None],
        [{'id': '', 'name': 'Missing id'}],
    )
    assert models == [{'id': 'web-chatgpt', 'name': 'ChatGPT', 'platform': 'chatgpt'}]


def test_opencode_snippet_contains_provider_and_models():
    payload = json.loads(build_opencode(BASE_URL, API_KEY, MODELS))
    assert payload['provider']['chatbridge']['options'] == {
        'baseURL': BASE_URL, 'apiKey': API_KEY,
    }
    assert set(payload['provider']['chatbridge']['models']) == {
        'chatgpt', 'custom:reasoner',
    }
    assert payload['model'] == 'chatbridge/chatgpt'


def test_hermes_snippet_has_yaml_provider_and_env_key():
    snippet = build_hermes(BASE_URL, API_KEY, MODELS)
    assert 'provider: chatbridge' in snippet
    assert 'base_url: ' + BASE_URL in snippet
    assert 'custom:reasoner: {}' in snippet
    assert 'CHATBRIDGE_API_KEY=' + API_KEY in snippet


def test_generic_presets_are_listed_with_rendered_snippets():
    presets = list_presets(BASE_URL, API_KEY, MODELS)
    by_id = {preset['id']: preset for preset in presets}
    assert {'opencode', 'hermes', 'generic-env', 'curl'} <= set(by_id)
    assert 'OPENAI_BASE_URL=' + BASE_URL in by_id['generic-env']['snippet']
    assert API_KEY in by_id['curl']['snippet']


def test_opencode_uses_fallback_model_for_empty_registry():
    payload = json.loads(build_opencode(BASE_URL, API_KEY, []))
    assert payload['model'] == 'chatbridge/web-chatgpt'
    assert payload['provider']['chatbridge']['models'] == {}
