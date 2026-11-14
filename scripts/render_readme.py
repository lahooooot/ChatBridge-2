"""Render the shipped English README, with a dependency-free fallback."""
import html
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
text = (ROOT/'README.md').read_text(encoding='utf-8')
try:
    import markdown
    body = markdown.markdown(text, extensions=['fenced_code','tables'])
except ImportError:
    body = '<pre>'+html.escape(text)+'</pre>'
page = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>ChatBridge 2.60.0 — Guide</title><style>body{font:16px/1.7 system-ui;max-width:980px;margin:40px auto;padding:0 24px;color:#dbe4f1;background:#141b27}a{color:#70e0c3}pre,code{background:#0e131c;white-space:pre-wrap;overflow-wrap:anywhere}pre{padding:16px;border-radius:9px}h1,h2{color:#fff}strong{color:#fff}</style><body>'+body+'</body></html>\n'
(ROOT/'README.html').write_text(page,encoding='utf-8')
print(ROOT/'README.html')
