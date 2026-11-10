import sys, time
sys.path.insert(0, '.')

print('python:', sys.version.split()[0])
try:
    import pytest
    print('pytest:', pytest.__version__)
except Exception as exc:
    print('pytest: MISSING ->', exc)

from desktop.internal_browser import InternalBrowser

class Bridge:
    port = 8787
    token = 'fake'

class HangingWindow:
    def evaluate_js(self, script, callback=None):
        time.sleep(999)

class GoodWindow:
    def evaluate_js(self, script, callback=None):
        return {'ok': True}

ok = True
d = InternalBrowser(Bridge(), lambda e: None)
d.window = HangingWindow()

start = time.monotonic()
try:
    d.evaluate('1', timeout=1)
    print('FAIL: expected TimeoutError on hung call'); ok = False
except TimeoutError as exc:
    print('hung call timed out as expected:', exc)
elapsed = time.monotonic() - start
print('bounded wait: %.2fs' % elapsed)
if elapsed > 8:
    print('FAIL: wait was not bounded'); ok = False

d.window = GoodWindow()
start = time.monotonic()
try:
    out = d.evaluate('2', timeout=5)
    print('recovered after %.2fs, result=%s' % (time.monotonic() - start, out))
except Exception as exc:
    print('FAIL: still blocked ->', exc); ok = False

try:
    out = d.evaluate('3', timeout=5)
    print('second call ok, result=%s' % (out,))
except Exception as exc:
    print('FAIL: lock unusable after recovery ->', exc); ok = False

print('RESULT:', 'PASS' if ok else 'FAIL')
