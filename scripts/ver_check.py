"""Fail the build when a shipped version marker drifts."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = '2.60.0'
CHECKS = {
    'desktop/app.py': r"APP_VERSION\s*=\s*['\"]([^'\"]+)",
    'desktop/agent_cb.js': r"VER\s*=\s*['\"]([^'\"]+)",
    'ChatBridge.iss': r'MyAppVersion\s+"([^"]+)"',
    'build_installer.bat': r'APP_VERSION=([^\s]+)',
}

def main():
    for file, pattern in CHECKS.items():
        match = re.search(pattern, (ROOT/file).read_text(encoding='utf-8'))
        assert match and match.group(1) == VERSION, f'Version mismatch: {file}'
    assert json.loads((ROOT/'shared/protocol.json').read_text())['version'] == VERSION
    for file in ('desktop/ui/index.html','README.md','README.html','ChatBridge.spec'):
        assert VERSION in (ROOT/file).read_text(encoding='utf-8'), f'Missing version in {file}'
    print('Version markers are synchronized:', VERSION)

if __name__ == '__main__':
    main()
