import re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
version = re.search(r"APP_VERSION\s*=\s*['\"]([^'\"]+)", (ROOT/'desktop/app.py').read_text()).group(1)
for name, pattern, replacement in (
    ('ChatBridge.iss', r'(#define MyAppVersion\s+")[^"]+(".*)', lambda m: m[1]+version+m[2]),
    ('build_installer.bat', r'(?m)^set APP_VERSION=.*$', lambda m: 'set APP_VERSION='+version),
):
    path = ROOT/name
    path.write_text(re.sub(pattern, replacement, path.read_text()), encoding='utf-8')
print('Installer version:', version)
