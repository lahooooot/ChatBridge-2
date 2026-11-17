"""Single source of truth for the models the local provider server exposes.

The provider turns ChatBridge web models into an OpenAI-compatible API.  The
exposed model list must follow the platforms the user actually configured
(built-in web chats plus custom models), so it lives in one module instead of
being duplicated inside the HTTP server.
"""
from __future__ import annotations

MODEL_PREFIX = 'web-'

BUILTIN_PLATFORM_NAMES = {
    'chatgpt': 'ChatGPT',
    'claude': 'Claude',
    'zai': 'z.ai',
    'deepseek': 'DeepSeek',
    'gemini': 'Gemini',
}


def model_id_for(platform: str) -> str:
    """Return the provider model id for a platform id."""
    text = str(platform or '').strip()
    if not text:
        return ''
    return MODEL_PREFIX + text


def platform_for_model(model_id: str) -> str:
    """Return the platform id behind a provider model id."""
    text = str(model_id or '').strip()
    if text.startswith(MODEL_PREFIX):
        return text[len(MODEL_PREFIX):]
    return text


def platform_name(platform: str, fallback: str = '') -> str:
    """Return a human readable name for a platform id."""
    return BUILTIN_PLATFORM_NAMES.get(platform, fallback or platform)


def build_models(platforms=None, custom_models=None) -> list[dict]:
    """Build the provider model list from platform rows and custom models.

    ``platforms`` holds ``{'id', 'name', 'home'}`` rows for the built-in web
    chats and ``custom_models`` is the config list of user added models.
    Every row becomes one provider model named ``web-<platform id>``; the
    platform mapping stays explicit so custom ids keep working.
    """
    models: list[dict] = []
    seen: set[str] = set()
    for row in list(platforms or []) + list(custom_models or []):
        if not isinstance(row, dict):
            continue
        platform = str(row.get('id') or '').strip()
        if not platform or platform in seen:
            continue
        seen.add(platform)
        name = str(row.get('name') or '').strip() or platform_name(platform)
        models.append({'id': model_id_for(platform), 'name': name, 'platform': platform})
    return models


def default_models() -> list[dict]:
    """Return the built-in model list used when no configuration is available."""
    return build_models([{'id': key, 'name': name}
                          for key, name in BUILTIN_PLATFORM_NAMES.items()])
