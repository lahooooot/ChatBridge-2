"""Self-update support for the portable Windows build.

ChatBridge ships as a single portable ``ChatBridge-X.Y.Z.exe``. Updating in
place must not require an installer:

1. Ask GitHub for the latest release.
2. If its ``tag_name`` (``vX.Y.Z``) is newer than :data:`APP_VERSION`, return
   the release metadata and the first ``.exe`` asset.
3. Download the asset next to the running executable, then hand off to a tiny
   batch script that waits for this process to exit, replaces the exe and
   relaunches it.

Everything here is defensive: a missing network, no releases, a rate limit or
an unparseable version must degrade to ``{'ok': False, 'reason': ...}`` and
never raise into the UI.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

GITHUB_OWNER = 'lahooooot'
GITHUB_REPO = 'ChatBridge-2'
API_LATEST = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest'
USER_AGENT = 'ChatBridge-Updater'
_TIMEOUT = 15


def _parse_version(value: str) -> tuple[int, ...]:
    """Turn ``v2.70.0`` (or ``2.70.0``) into a comparable tuple."""
    numbers = re.findall(r'\d+', str(value or ''))
    if not numbers:
        return ()
    return tuple(int(n) for n in numbers[:4])


def is_newer(candidate: str, current: str) -> bool:
    """True when *candidate* is a strictly newer dotted version."""
    a, b = _parse_version(candidate), _parse_version(current)
    if not a:
        return False
    # Pad so 2.70 and 2.70.0 compare equal.
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def _fetch_latest() -> dict[str, Any]:
    request = urllib.request.Request(API_LATEST, headers={
        'User-Agent': USER_AGENT,
        'Accept': 'application/vnd.github+json',
    })
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        return json.load(response)


def _pick_exe(release: dict[str, Any]) -> dict[str, Any] | None:
    """Prefer a portable ``ChatBridge-*.exe``; fall back to any ``.exe`` asset."""
    assets = release.get('assets') or []
    exes = [a for a in assets if str(a.get('name', '')).lower().endswith('.exe')]
    if not exes:
        return None
    portable = [a for a in exes if str(a.get('name', '')).lower().startswith('chatbridge-')]
    chosen = (portable or exes)[0]
    return {
        'name': chosen.get('name'),
        'url': chosen.get('browser_download_url'),
        'size': chosen.get('size'),
    }


def check_for_update(current_version: str) -> dict[str, Any]:
    """Return update metadata without mutating anything.

    Shape on success::

        {'ok': True, 'update_available': bool, 'current': ..., 'latest': ...,
         'url': <release html url>, 'notes': <body>, 'asset': {...} | None}
    """
    try:
        release = _fetch_latest()
    except Exception as exc:  # network, rate limit, JSON, DNS…
        return {'ok': False, 'reason': 'network', 'error': str(exc)[:300]}
    latest = str(release.get('tag_name') or release.get('name') or '').strip()
    available = is_newer(latest, current_version)
    return {
        'ok': True,
        'update_available': available,
        'current': current_version,
        'latest': latest.lstrip('vV'),
        'tag': latest,
        'url': release.get('html_url'),
        'notes': (release.get('body') or '')[:4000],
        'asset': _pick_exe(release),
    }


def _running_exe() -> Path | None:
    """The on-disk .exe for a frozen build, else None (source checkout)."""
    if not getattr(sys, 'frozen', False):
        return None
    return Path(sys.executable).resolve()


def apply_update(asset_url: str, expected_name: str = '') -> dict[str, Any]:
    """Download *asset_url* and schedule an in-place replace + relaunch.

    Only works for the frozen portable EXE. Source checkouts get a clear
    ``not-frozen`` reason so the UI can tell the user to update manually.
    """
    target = _running_exe()
    if target is None:
        return {'ok': False, 'reason': 'not-frozen',
                'error': 'Self-update only works in the packaged EXE.'}
    if not asset_url or not str(asset_url).lower().endswith('.exe'):
        return {'ok': False, 'reason': 'bad-asset', 'error': 'No downloadable EXE in the release.'}
    workdir = Path(tempfile.gettempdir()) / 'chatbridge-update'
    try:
        workdir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {'ok': False, 'reason': 'fs', 'error': str(exc)[:300]}
    staged = workdir / (expected_name or target.name)
    try:
        request = urllib.request.Request(asset_url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response, open(staged, 'wb') as handle:
            shutil.copyfileobj(response, handle, length=1024 * 256)
    except Exception as exc:
        return {'ok': False, 'reason': 'download', 'error': str(exc)[:300]}
    if staged.stat().st_size < 1024 * 256:
        return {'ok': False, 'reason': 'download', 'error': 'Downloaded file looks incomplete.'}

    # A batch script survives our exit and can overwrite the locked .exe.
    script = workdir / 'apply_update.bat'
    pid = os.getpid()
    bat = (
        '@echo off\r\n'
        'setlocal\r\n'
        f'title ChatBridge update\r\n'
        f':wait{pid}\r\n'
        f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul\r\n'
        'if not errorlevel 1 (\r\n'
        '  timeout /t 1 /nobreak >nul\r\n'
        f'  goto wait{pid}\r\n'
        ')\r\n'
        f'copy /y "{staged}" "{target}" >nul\r\n'
        f'start "" "{target}"\r\n'
        'del "%~f0" >nul 2>&1\r\n'
    )
    try:
        script.write_text(bat, encoding='utf-8')
        subprocess.Popen(['cmd', '/c', str(script)],
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                         close_fds=True)
    except Exception as exc:
        return {'ok': False, 'reason': 'launch', 'error': str(exc)[:300]}
    return {'ok': True, 'staged': str(staged), 'target': str(target),
            'relaunching': True}
