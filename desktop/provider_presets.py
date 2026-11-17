"""Ready-to-paste provider snippets for OpenAI-compatible desktop agents.

ChatBridge exposes its web models as an OpenAI-compatible endpoint, so every
agent that speaks that protocol can use them.  The registry below keeps the
agent specific part declarative: adding another agent is one entry, and the
generic presets cover every client that follows the OpenAI convention.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PROVIDER_ID = 'chatbridge'
PROVIDER_NAME = 'ChatBridge'
KEY_ENV = 'CHATBRIDGE_API_KEY'
OPENAI_COMPATIBLE_NPM = '@ai-sdk/openai-compatible'
NEWLINE = chr(10)


def _home() -> Path:
    return Path.home()


def _local_app_data() -> Path:
    value = os.environ.get('LOCALAPPDATA')
    return Path(value) if value else _home() / 'AppData' / 'Local'


def opencode_config_path() -> Path:
    """Return the opencode configuration file path."""
    return _home() / '.config' / 'opencode' / 'opencode.json'


def hermes_config_path() -> Path:
    """Return the Hermes (Nous Research) configuration file path."""
    return _local_app_data() / 'hermes' / 'config.yaml'


def hermes_env_path() -> Path:
    """Return the Hermes environment file path."""
    return _local_app_data() / 'hermes' / '.env'


def _entries(models) -> list[dict]:
    rows = []
    for model in models or []:
        if isinstance(model, dict):
            model_id = str(model.get('id') or '').strip()
            name = str(model.get('name') or '').strip() or model_id
        else:
            model_id = str(model or '').strip()
            name = model_id
        if model_id:
            rows.append({'id': model_id, 'name': name})
    return rows


def _first(models) -> str:
    rows = _entries(models)
    return rows[0]['id'] if rows else 'web-chatgpt'


def build_opencode(base_url: str, key: str, models=None) -> str:
    """Return an opencode.json provider block for ChatBridge."""
    payload = {
        '$schema': 'https://opencode.ai/config.json',
        'provider': {
            PROVIDER_ID: {
                'npm': OPENAI_COMPATIBLE_NPM,
                'name': PROVIDER_NAME,
                'options': {'baseURL': base_url, 'apiKey': key},
                'models': {row['id']: {'name': row['name']} for row in _entries(models)},
            }
        },
        'model': PROVIDER_ID + '/' + _first(models),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_hermes(base_url: str, key: str, models=None) -> str:
    """Return a Hermes config.yaml provider block plus the matching .env line."""
    rows = _entries(models)
    lines = ['# ChatBridge provider for Hermes - merge this into config.yaml',
             'model:',
             '  default: ' + _first(models),
             '  provider: ' + PROVIDER_ID,
             '  base_url: ' + base_url,
             '  key_env: ' + KEY_ENV,
             'providers:',
             '  ' + PROVIDER_ID + ':',
             '    name: ' + PROVIDER_NAME,
             '    base_url: ' + base_url,
             '    model: ' + _first(models),
             '    discover_models: true',
             '    models:']
    lines.extend('      ' + row['id'] + ': {}' for row in rows)
    lines.append('    key_env: ' + KEY_ENV)
    lines.append('')
    lines.append('# add this line to ' + str(hermes_env_path()) + ':')
    lines.append(KEY_ENV + '=' + key)
    return NEWLINE.join(lines)


def build_generic_json(base_url: str, key: str, models=None) -> str:
    """Return a generic JSON provider block for OpenAI-compatible clients."""
    payload = {'provider': {PROVIDER_ID: {
        'npm': OPENAI_COMPATIBLE_NPM,
        'name': PROVIDER_NAME,
        'options': {'baseURL': base_url, 'apiKey': key},
        'models': {row['id']: {'name': row['name']} for row in _entries(models)},
    }}}
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_generic_yaml(base_url: str, key: str, models=None) -> str:
    """Return a generic YAML provider block for OpenAI-compatible clients."""
    rows = _entries(models)
    lines = ['provider:',
             '  ' + PROVIDER_ID + ':',
             '    name: ' + PROVIDER_NAME,
             '    base_url: ' + base_url,
             '    api_key: ' + key,
             '    model: ' + _first(models),
             '    models:']
    lines.extend('      ' + row['id'] + ': {}' for row in rows)
    return NEWLINE.join(lines)


def build_generic_env(base_url: str, key: str, models=None) -> str:
    """Return environment variables for agents that follow the OpenAI names."""
    rows = _entries(models)
    lines = ['OPENAI_BASE_URL=' + base_url,
             'OPENAI_API_KEY=' + key,
             'OPENAI_MODEL=' + _first(models),
             '# available models: ' + ', '.join(row['id'] for row in rows)]
    return NEWLINE.join(lines)


def build_curl(base_url: str, key: str, models=None) -> str:
    """Return a direct curl call against the provider endpoint."""
    payload = json.dumps({'model': _first(models),
                          'messages': [{'role': 'user', 'content': 'Hello'}]},
                         ensure_ascii=False)
    return ('curl ' + base_url + '/chat/completions -H "Content-Type: application/json" '
            '-H "Authorization: Bearer ' + key + '" -d ' + payload)


PRESETS = [
    {'id': 'opencode', 'label': 'opencode', 'format': 'json',
     'config_path': opencode_config_path, 'build': build_opencode,
     'note': 'Merge the provider block into opencode.json and keep the existing keys.'},
    {'id': 'hermes', 'label': 'Hermes', 'format': 'yaml',
     'config_path': hermes_config_path, 'build': build_hermes,
     'note': 'Merge into config.yaml and add the key line to the Hermes .env file.'},
    {'id': 'generic-json', 'label': 'Any agent (JSON)', 'format': 'json',
     'config_path': None, 'build': build_generic_json,
     'note': 'Generic OpenAI-compatible provider block for JSON based clients.'},
    {'id': 'generic-yaml', 'label': 'Any agent (YAML)', 'format': 'yaml',
     'config_path': None, 'build': build_generic_yaml,
     'note': 'Generic OpenAI-compatible provider block for YAML based clients.'},
    {'id': 'generic-env', 'label': 'Any agent (environment)', 'format': 'env',
     'config_path': None, 'build': build_generic_env,
     'note': 'Base URL, key and model as environment variables.'},
    {'id': 'curl', 'label': 'Terminal (curl)', 'format': 'shell',
     'config_path': None, 'build': build_curl,
     'note': 'Direct API call to verify the provider from a terminal.'},
]


def list_presets(base_url: str = '', key: str = '', models=None) -> list[dict]:
    """Return the preset descriptors, each with a ready-to-paste snippet."""
    result = []
    for preset in PRESETS:
        path = preset.get('config_path')
        result.append({'id': preset['id'], 'label': preset['label'],
                       'format': preset['format'], 'note': preset['note'],
                       'config_path': str(path()) if path else '',
                       'snippet': preset['build'](base_url, key, models)})
    return result


def build_snippet(preset_id: str, base_url: str, key: str, models=None) -> str:
    """Return the snippet of a single preset."""
    for preset in PRESETS:
        if preset['id'] == preset_id:
            return preset['build'](base_url, key, models)
    raise ValueError('Unknown provider preset: ' + str(preset_id))
