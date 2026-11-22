from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / 'desktop' / 'ui' / 'app.js'


def test_paste_modal_hides_the_native_browser():
    """The native WebView2 window sits above the DOM, so every modal that opens
    while the browser is docked must be in the ``visible`` guard and must call
    sendIbFit on open and close. This pins the Paste-a-tool-request fix."""
    js = APP_JS.read_text(encoding='utf-8')
    assert "!$('pasteModal').open" in js, 'pasteModal must be part of the ibDock visible guard'
    assert "$('pasteModal').showModal();sendIbFit();" in js, 'opening pasteModal must refit the browser'
    assert "$('pasteModal').addEventListener('close',sendIbFit)" in js, 'closing pasteModal must refit the browser'
