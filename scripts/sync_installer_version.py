"""Copy APP_VERSION into the files Inno Setup and the build scripts read.

Runs before ISCC. Also proves the installer no longer hardcodes an
older executable name: every EXE reference must go through
``{#MyAppExeName}`` so a version bump cannot leave a stale filename.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
version = re.search(r"APP_VERSION\s*=\s*['\"]([^'\"]+)", (ROOT / 'desktop/app.py').read_text()).group(1)

for name, pattern, replacement in (
    ('ChatBridge.iss', r'(#define MyAppVersion\s+")[^"]+(".*)', lambda m: m[1] + version + m[2]),
    ('build_installer.bat', r'(?m)^set APP_VERSION=.*$', lambda m: 'set APP_VERSION=' + version),
):
    path = ROOT / name
    path.write_text(re.sub(pattern, replacement, path.read_text()), encoding='utf-8')

# Guard: a literal ChatBridge-<digits>.<digits>.<digits>.exe in the Inno
# script means a version bump would point at a file that does not exist.
iss = (ROOT / 'ChatBridge.iss').read_text(encoding='utf-8')
stale = re.findall(r'ChatBridge-\d+\.\d+\.\d+\.exe', iss)
if stale:
    sys.exit(
        'ChatBridge.iss still hardcodes ' + ', '.join(sorted(set(stale)))
        + '; use {#MyAppExeName} instead.'
    )

print('Installer version:', version)
