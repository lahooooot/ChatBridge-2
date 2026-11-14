#!/usr/bin/env python3
"""Independent Chromium DOM-contract checks; no live account or network required.

Run: python3 scripts/visual_check_agent.py [--headed] [--filter substring]
Every case gets a fresh browser context; a failure never suppresses later cases.
This verifies the page agent, NOT the Python driver's capture/parser state machine.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Callable

from playwright.sync_api import Browser, Page, sync_playwright

AGENT = Path(__file__).resolve().parents[1] / "desktop" / "agent_cb.js"
URLS = {
    "chatgpt": "https://chatgpt.com/c/current",
    "claude": "https://claude.ai/chat/current",
    "zai": "https://chat.z.ai/c/current",
    "deepseek": "https://chat.deepseek.com/a/chat/s/current",
    "gemini": "https://gemini.google.com/app/current",
    "generic": "https://mock.chatbridge.test/chat/current",
}
OLD = "A previous assistant answer that must never be mistaken for the new response."
NEW = "A fresh assistant answer with enough content to qualify as a generic response."
STYLE = """<style>
body{font:16px system-ui;margin:20px}main{max-width:800px}
form,fieldset{margin-top:30px;padding:10px;border:1px solid #aaa}
textarea,[contenteditable=true]{display:block;min-height:70px;width:650px}
button,[role=button]{display:inline-block;min-height:32px;min-width:40px;padding:6px}
.ds-button--primary svg{width:24px;height:24px} .sr-only{position:absolute;width:1px;height:1px;overflow:hidden}
pre{white-space:pre-wrap;background:#eee;padding:10px} .dot{width:12px;height:12px;background:#999}
.chat-user,.chat-assistant,.ds-message,model-response,user-query,article{display:block;min-height:30px;padding:8px}
</style>"""


def check(condition: object, message: str, detail: object = "") -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail}" if detail != "" else message)


def api(page: Page, name: str, *args: object) -> object:
    return page.evaluate("([name,args]) => window.__CB__[name](...args)", [name, list(args)])


def old_messages(platform: str) -> str:
    if platform == "chatgpt":
        return f'<div data-turn-key="old-user"><div data-content-search-unit-key="old:user" data-message-author-role="user">Old user</div></div><div data-turn-key="old-assistant"><div data-content-search-unit-key="old:assistant"><span class="sr-only">ChatGPT said:</span><div data-markdown-text-style><p>{OLD}</p></div></div></div>'
    if platform == "claude":
        return f'<div data-testid="transcript-row" data-perf-row="human">Old user</div><div data-testid="transcript-row" data-perf-row="assistant"><div data-testid="assistant-message"><div class="font-claude-message"><p>{OLD}</p></div></div></div>'
    if platform == "zai":
        return f'<div class="chat-user">Old user</div><div class="chat-assistant"><div class="markdown-prose"><p>{OLD}</p></div></div>'
    if platform == "deepseek":
        return f'<div class="ds-message">Old user</div><div class="ds-message"><div class="ds-markdown ds-assistant-message-main-content"><p>{OLD}</p></div></div>'
    if platform == "gemini":
        return f'<user-query>Old user</user-query><model-response><message-content><p>{OLD}</p></message-content></model-response>'
    return f'<article><p>{OLD}</p></article>'


def editor_markup(platform: str, editable: bool = False) -> str:
    if platform == "chatgpt":
        return '<div data-editor id="prompt-textarea" contenteditable="true"></div><button data-submit data-testid="send-button" type="button">Send</button>'
    if platform == "claude":
        return '<div data-editor class="ProseMirror" contenteditable="true"></div><button data-submit aria-label="Send Message" type="button">Send</button>'
    if platform == "zai":
        return '<textarea data-editor id="chat-input"></textarea><button data-submit id="send-message-button" type="button">Send</button>'
    if platform == "deepseek":
        return '<textarea data-editor name="search" placeholder="Message DeepSeek"></textarea><div data-submit role="button" class="ds-button--primary ds-button--disabled" aria-disabled="true"><svg viewBox="0 0 24 24"><path d="M12 20V4M4 12l8-8 8 8"/></svg></div>'
    if platform == "gemini":
        return '<rich-textarea><div data-editor class="ql-editor" contenteditable="true"></div></rich-textarea><button data-submit class="send-button" type="button">Send</button>'
    ed = '<div data-editor contenteditable="true"></div>' if editable else '<textarea data-editor></textarea>'
    return ed + '<button data-submit type="button" aria-label="Send">Send</button>'


FRONTEND = r"""(platform => {
const editor = document.querySelector('[data-editor]');
const send = document.querySelector('[data-submit]');
const messages = document.getElementById('messages');
window.mock = {sent:0, paste:0, focus:[], enter:0, stopped:0, mode:'normal'};
const getText = () => 'value' in editor ? editor.value : editor.textContent;
const setText = value => { if ('value' in editor) editor.value = value; else editor.textContent = value; };
function enable() { if(platform === 'deepseek') {send.classList.toggle('ds-button--disabled', !getText());send.setAttribute('aria-disabled', getText() ? 'false':'true');} }
editor.addEventListener('input', enable);
editor.addEventListener('paste', e => {
 if(e.clipboardData && e.clipboardData.getData('text/plain')) {e.preventDefault();setText(e.clipboardData.getData('text/plain'));window.mock.paste++;enable();}
});
window.mockUser = text => {
 const el = document.createElement(platform === 'gemini' ? 'user-query':'div');
 if(platform === 'chatgpt') {el.setAttribute('data-content-search-unit-key','new'+mock.sent+':user');el.setAttribute('data-message-author-role','user');}
 if(platform === 'claude') {el.setAttribute('data-testid','transcript-row');el.setAttribute('data-perf-row','human');}
 if(platform === 'zai') el.className = 'chat-user';
 if(platform === 'deepseek') el.className = 'ds-message';
 el.textContent = text;messages.append(el);return el;
};
window.mockAssistant = html => {
 const el = document.createElement(platform === 'gemini' ? 'model-response':platform === 'generic' ? 'article':'div');
 if(platform === 'chatgpt') {el.setAttribute('data-content-search-unit-key','new'+mock.sent+Math.random()+':assistant');el.innerHTML='<div data-markdown-text-style>'+html+'</div>';}
 if(platform === 'claude') {el.setAttribute('data-testid','assistant-message');el.innerHTML='<div class="font-claude-message">'+html+'</div>';}
 if(platform === 'zai') {el.className='chat-assistant';el.innerHTML='<div class="markdown-prose">'+html+'</div>';}
 if(platform === 'deepseek') {el.className='ds-message';el.innerHTML='<div class="ds-markdown ds-assistant-message-main-content">'+html+'</div>';}
 if(platform === 'gemini') el.innerHTML='<message-content>'+html+'</message-content>';
 if(platform === 'generic') el.innerHTML=html;
 messages.append(el);return el;
};
function submit() {
 mock.focus.push(document.activeElement === editor || editor.contains(document.activeElement));
 if(!mock.focus.at(-1) || !getText()) return;
 if(mock.mode === 'stuck') return;
 mock.sent++;
 const text = getText();setText('');enable();
 if(mock.mode === 'drop') return;
 const accepted = () => {
  if(mock.mode !== 'optimistic') mockUser(text);
  if(mock.mode === 'optimistic') document.querySelector('[data-optimistic]').innerHTML='<div data-markdown-text-style><p>RESPONSE</p></div>';
  else mockAssistant('<p>RESPONSE</p>');
  if(platform === 'deepseek') {send.classList.remove('ds-button--disabled');send.setAttribute('aria-disabled','false');send.innerHTML='<svg viewBox="0 0 24 24"><rect x="5" y="5" width="14" height="14"/></svg>';}
  else document.getElementById('mock-stop').style.display='inline-block';
 };
 if(mock.mode === 'delayed') setTimeout(accepted,900); else accepted();
}
send.addEventListener('click', () => {
 if(platform === 'deepseek' && send.querySelector('rect')) {mock.stopped++;send.innerHTML='<svg viewBox="0 0 24 24"><path d="M12 20V4"/></svg>';enable();return;}
 submit();
});
editor.addEventListener('keydown',e => { if(e.key==='Enter') {mock.enter++;e.preventDefault();submit();} });
document.getElementById('mock-stop').addEventListener('click',e => {mock.stopped++;e.currentTarget.style.display='none';});
if(platform === 'claude' || platform === 'chatgpt') document.execCommand = () => false;
})(PLATFORM);""".replace("RESPONSE", NEW)


class Suite:
    def __init__(self, browser: Browser, source: str) -> None:
        self.browser = browser
        self.source = source
        self.context = None

    def page(self, platform: str = "chatgpt", *, editable: bool = False, extra: str = "", messages: str | None = None, frontend: bool = True) -> Page:
        self.close()
        self.context = self.browser.new_context(viewport={"width": 1100, "height": 900})
        page = self.context.new_page()
        html = '<!doctype html><html><head><title>Mock ChatBridge</title>' + STYLE + '</head><body><nav id="sidebar"></nav><main><div id="messages">' + (old_messages(platform) if messages is None else messages) + '</div>' + extra + '<form onsubmit="return false">' + editor_markup(platform, editable) + '<input type="file" style="display:none"><div id="chips"></div><button id="mock-stop" aria-label="Stop generating" type="button" style="display:none">Stop</button></form></main></body></html>'
        page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=html))
        page.goto(URLS[platform], wait_until="domcontentloaded")
        if frontend:
            page.evaluate(FRONTEND.replace("PLATFORM", json.dumps(platform)))
        page.evaluate(self.source)
        return page

    def close(self) -> None:
        if self.context:
            self.context.close()
            self.context = None


def platform_send(suite: Suite, platform: str, editable: bool = False) -> None:
    page = suite.page(platform, editable=editable)
    check(api(page, "ping") == "pong", "ping contract")
    meta = api(page, "meta")
    check(meta["version"] == "2.60.0" and meta["platform"] == platform, "platform metadata", meta)
    probe = api(page, "probe")
    check(probe["ready"] and probe["editor_selector"], "editor discovery", probe)
    baseline = api(page, "baseline")
    check(baseline["last"] == OLD, "baseline contains previous response", baseline)
    result = api(page, "send", "Hello from the user's local bridge")
    check(result["ok"] and result["verdict"] == "accepted", "verified send", result)
    snap = api(page, "snap")
    check(NEW in snap["text"] and OLD not in snap["text"], "new turn only", snap)
    check(snap["count"] > baseline["count"], "assistant count grows", snap)
    check(all(page.evaluate("mock.focus")), "send always focused")
    if platform in {"chatgpt", "claude"}:
        check(page.evaluate("mock.paste") == 1 and result["how"].startswith("paste"), "paste path", result)
    if platform != "generic":
        check(snap["busy"], "stop mode means busy", snap)
        stopped = api(page, "stop")
        check(stopped["ok"] and page.evaluate("mock.stopped") == 1, "stop clicked", stopped)
        check(not api(page, "snap")["busy"], "busy clears after stop")
    check(api(page, "readChat")["messages"][-1]["role"] == "assistant", "transcript order")


def test_optimistic(suite: Suite) -> None:
    page = suite.page("chatgpt")
    page.evaluate("""mockUser('Optimistic user');const e=mockAssistant('');e.setAttribute('data-optimistic','');mock.mode='optimistic';""")
    baseline = api(page, "baseline")
    check(baseline["count"] == 2 and baseline["last"] == "", "optimistic empty unit baseline", baseline)
    result = api(page, "send", "Fill the already-created optimistic unit")
    snap = api(page, "snap")
    check(result["ok"] and snap["count"] == baseline["count"] and snap["text"] == NEW, "optimistic movement without count growth", snap)


def test_multi(suite: Suite, platform: str) -> None:
    page = suite.page(platform)
    page.evaluate("""mockUser('Current user');mockAssistant('<p>First unit</p>');mockAssistant('<p>Second unit</p>');mockAssistant('<p>Third unit</p>');""")
    snap = api(page, "snap")
    check(snap["count"] == 4, "all assistant units counted", snap)
    check(snap["text"] == "First unit\n\nSecond unit\n\nThird unit", "all units after last user", snap)
    transcript = api(page, "readChat")
    check([m["role"] for m in transcript["messages"]] == ["user", "assistant", "user", "assistant", "assistant", "assistant"], "ordered multi-unit transcript", transcript)


def test_markdown(suite: Suite) -> None:
    page = suite.page("deepseek", messages="")
    page.evaluate(r"""mockUser('Read this');mockAssistant(`<span class="sr-only">ChatGPT said:</span><h2>Heading</h2><p><strong>Bold</strong> <em>Italic</em> <del>Gone</del> <code>a|b</code><br>Next <a href="javascript:alert(1)">unsafe</a> <a href="/files/a.txt">file</a></p><ul><li>One<ul><li>Nested</li></ul></li><li>Two</li></ul><ol start="3"><li>Three</li></ol><blockquote><p>Quote</p></blockquote><hr><table><tr><th>A|B</th><th>C</th></tr><tr><td>x</td><td>y</td></tr></table><div><span>chatbridge-tool-call</span><button>Copy</button><pre><code>{"tool":"read_file","args":{"path":"demo.py"}}</code></pre></div><div><span>chatbridge</span><pre><code data-language="json">{"example":"explicit language wins"}</code></pre></div><div><span>text</span><pre><code>fence inside: \`\`\`</code></pre></div><div class="thinking"><span>Thinking…</span><p>Secret reasoning</p></div><button>Copy answer</button><script>console.log('leak')</script><p>Thought for 5 seconds</p><p>Searching…</p><p>Real ending</p><p>&lt;ds_safety&gt;discard&lt;/ds_safety&gt;Safe</p>`);""")
    snap = api(page, "snap")
    text = snap["text"]
    for expected in ["## Heading", "**Bold**", "*Italic*", "~~Gone~~", "`a|b`", "[file](https://chat.deepseek.com/files/a.txt)", "- One", "Nested", "3. Three", "> Quote", "---", "| A\\|B | C |", "```chatbridge-tool-call\n", "```json\n", "````text\nfence inside: ```\n````", "Real ending"]:
        check(expected in text, f"Markdown keeps {expected!r}", text)
    for unwanted in ["ChatGPT said:", "Copy", "Secret reasoning", "Searching", "Thought for", "discard", "ds_safety", "javascript:", "console.log"]:
        check(unwanted not in text, f"Markdown skips {unwanted!r}", text)
    check("Secret reasoning" in snap["think"] and snap["think_active"], "thinking captured separately", snap)


def test_banner_collapse(suite: Suite) -> None:
    page = suite.page("deepseek", messages="")
    page.evaluate("""mockAssistant('<div><span>chatbridge-tool-call</span><pre><code>{"tool":"read_file","args":{"path":"x"}}</code></pre></div>');""")
    first = api(page, "snap")["text"]
    # Watcher sweeps also cover mutations arriving after initial injection.
    page.wait_for_timeout(1700)
    check(page.locator('[data-cb-ui="tool-chip"]').count() == 1, "neutral tool chip")
    check(page.locator('pre').get_attribute('data-cb-tool') == 'collapsed', "raw block visually collapsed")
    check(api(page, "snap")["text"] == first and '"tool":"read_file"' in first, "collapse preserves readable original DOM")
    page.locator('[data-cb-ui="tool-chip"]').click()
    check(page.locator('pre').get_attribute('data-cb-tool') == 'expanded', "chip expands original block")


def test_shadow(suite: Suite) -> None:
    page = suite.page("chatgpt", messages="")
    page.evaluate("""mockUser('Shadow user');const unit=mockAssistant('');const host=document.createElement('dil-renderer');unit.replaceChildren(host);host.attachShadow({mode:'open'}).innerHTML='<div data-markdown-text-style><span class="sr-only">ChatGPT said:</span><h3>Shadow answer</h3><p><b>Nested</b> rendering works.</p><dil-child></dil-child></div>';host.shadowRoot.querySelector('dil-child').attachShadow({mode:'open'}).innerHTML='<p>Second shadow level</p><button>Copy secret</button>';""")
    text = api(page, "snap")["text"]
    check("### Shadow answer" in text and "**Nested**" in text and "Second shadow level" in text, "open shadow Markdown", text)
    check("Copy secret" not in text and "ChatGPT said:" not in text, "shadow overhead excluded", text)
    check(api(page, "readChat")["messages"][-1]["text"] == text, "shadow transcript")


def test_generic_diff(suite: Suite) -> None:
    page = suite.page("generic")
    baseline = api(page, "baseline")
    check(api(page, "snap")["text"] == "", "generic baseline excludes old leaf")
    page.evaluate("document.querySelector('#messages p').textContent += ' Updated with a new suffix.'")
    snap = api(page, "snap")
    check(snap["count"] == baseline["count"] and "new suffix" in snap["text"], "generic same-node text movement", snap)
    api(page, "baseline")
    page.evaluate("mockAssistant('<p>A newly appended generic response with more than forty characters.</p>')")
    text = api(page, "snap")["text"]
    check("newly appended" in text and "previous assistant" not in text, "generic new leaf diff", text)


def test_bottom_editor(suite: Suite) -> None:
    page = suite.page("generic", editable=True, extra='<textarea id="wrong-editor" style="position:absolute;top:0">Search box</textarea>')
    check(api(page, "probe")["editor_selector"] == "generic:lowest-editor", "generic fallback used")
    result = api(page, "send", "Choose the bottommost visible composer")
    check(result["ok"] and page.locator('#wrong-editor').input_value() == "Search box", "top editor left intact", result)


def test_enter_fallback(suite: Suite) -> None:
    page = suite.page("gemini")
    page.locator('[data-submit]').evaluate("el => el.remove()")
    result = api(page, "send", "Only Enter can send this message")
    check(result["ok"] and result["how"].endswith("+enter") and page.evaluate('mock.enter') == 1, "focused Enter fallback", result)


def test_deepseek_pow(suite: Suite, mode: str) -> None:
    page = suite.page("deepseek")
    page.evaluate("mode => mock.mode=mode", mode)
    result = api(page, "send", "Proof of work test")
    if mode == "drop":
        check(not result["ok"] and result["verdict"] == "dropped" and result["error"] == "send-dropped", "silent PoW drop reported", result)
        check(page.evaluate('mock.sent') == 3, "three verified PoW rounds", result)
    elif mode == "stuck":
        check(not result["ok"] and result["verdict"] == "stuck", "stuck composer reported", result)
        check(api(page, "snap")["composer"] == "Proof of work test", "manual Enter still has text")
    else:
        check(result["ok"] and result["verdict"] == "accepted" and page.evaluate('mock.sent') == 1, "PoW grace waits without duplicate", result)


def test_deepseek_controls(suite: Suite) -> None:
    page = suite.page("deepseek")
    check(not api(page, "snap")["busy"] and not api(page, "probe")["send"], "disabled empty arrow is idle")
    page.locator('[data-editor]').fill('Ready')
    check(api(page, "probe")["send"] and not api(page, "snap")["busy"], "enabled arrow and text is send mode")
    page.evaluate("document.querySelector('[data-editor]').value=''")
    check(api(page, "snap")["busy"], "enabled empty composer means generation")
    page.evaluate("document.querySelector('[data-submit]').innerHTML='<svg><rect width=12 height=12 x=2 y=2 /></svg>'")
    check(api(page, "probe")["stop"] and not api(page, "probe")["send"], "rect is stop, not arrow")


def test_busy_debounce(suite: Suite) -> None:
    page = suite.page("zai")
    api(page, "drain")
    page.wait_for_timeout(3200)
    events = api(page, "drain")["events"]
    check([e["busy"] for e in events if e["type"] == "platform_busy"] == [False], "two-read initial idle")
    page.evaluate("document.getElementById('messages').insertAdjacentHTML('afterend','<div id=" + '"pre-dot"' + " class=" + '"dot-flashing"' + " style=" + '"width:12px;height:12px"' + "></div>')")
    check(api(page, "snap")["busy"] and api(page, "snap")["stage"] == "writing", "pre-answer loading signal")
    page.wait_for_timeout(3200)
    events = api(page, "drain")["events"]
    check([e["busy"] for e in events if e["type"] == "platform_busy"] == [True], "debounced busy flip")
    page.locator('#pre-dot').evaluate("el => el.remove()")
    page.wait_for_timeout(3200)
    check([e["busy"] for e in api(page, "drain")["events"] if e["type"] == "platform_busy"] == [False], "debounced idle flip")


def test_placeholder_think(suite: Suite) -> None:
    page = suite.page("zai", messages="")
    page.evaluate(r"""mockAssistant('<p>Thinking…</p><p>Thought for 5 seconds</p><p>Searching...</p><p>Generating…</p><p>در حال فکر…</p><p>思考中</p><div class="thinking-panel"><button aria-expanded="false" onclick="this.setAttribute(\'aria-expanded\',\'true\');this.nextElementSibling.style.display=\'block\';mock.opened=(mock.opened||0)+1">Thinking…</button><div class="thinking-body" style="display:none">Reasoning separately</div></div>');""")
    snap = api(page, "snap")
    check(snap["text"] == "" and snap["stage"] == "thinking", "placeholder never becomes answer", snap)
    check("Reasoning separately" in snap["think"] and page.evaluate('mock.opened') == 1, "collapsed thinking expanded once", snap)
    api(page, "snap")
    check(page.evaluate('mock.opened') == 1, "no repeated thinking toggle")
    page.evaluate("document.querySelector('.thinking-panel button').textContent='Thought for 3s'")
    check(not api(page, "snap")["think_active"], "completed thinking not active")


def test_limits(suite: Suite) -> None:
    page = suite.page("chatgpt", extra='<aside>You\'ve reached our limit in this unrelated help article.</aside><div role="alert" style="display:none">You\'ve reached our limit</div>')
    check(api(page, "snap")["limits"] == [], "hidden and unrelated notices ignored")
    page.evaluate(r"""mockUser('new user');mockAssistant('<p>Normal reply</p>');document.querySelector('#messages').insertAdjacentHTML('afterend', '<div role="alert">You\'ve reached our limit</div>');""")
    limits = api(page, "snap")["limits"]
    check(len(limits) == 1 and limits[0]["where"] == "dialog", "scoped visible alert", limits)
    page.locator('[role=alert]').last.evaluate('el => el.remove()')
    page.evaluate("mockAssistant('<p>You are fine, but Upgrade for advanced models</p>')")
    check(any(l["kind"] == "hard" for l in api(page, "snap")["limits"]), "GPT free-plan tail notice")
    check(page.url.endswith('/c/current'), "limits never navigate automatically")


def test_upload(suite: Suite, strategy: str) -> None:
    page = suite.page("zai")
    page.evaluate("""strategy => {
      const chip=file=>{const e=document.createElement('span');e.className='file-chip';e.textContent=file.name;document.getElementById('chips').append(e);mock.fileType=file.type;};
      if(strategy==='input') document.querySelector('input[type=file]').addEventListener('change', e=>chip(e.target.files[0]));
      if(strategy==='drag') document.querySelector('[data-editor]').addEventListener('drop',e=>{e.preventDefault();chip(e.dataTransfer.files[0]);});
      if(strategy==='paste') document.querySelector('[data-editor]').addEventListener('paste',e=>{if(e.clipboardData.files.length){e.preventDefault();chip(e.clipboardData.files[0]);}});
    }""", strategy)
    result = api(page, "upload", "notes.text", "application/octet-stream", "data:application/octet-stream;base64,aGVsbG8=")
    check(result["ok"] and result["how"] == strategy and result["size"] == 5, "verified upload strategy", result)
    check(page.evaluate('mock.fileType') == 'text/plain', ".text MIME inferred")
    started = time.monotonic()
    check(api(page, "send", "Read the attachment")["ok"], "send after verified attachment")
    check(time.monotonic() - started >= 1.9, "post-file composer settle respected")


def test_upload_unverified(suite: Suite) -> None:
    page = suite.page("zai")
    page.evaluate("document.querySelector('[data-editor]').value='unverified.txt'")
    result = api(page, "upload", "unverified.txt", "text/plain", "data:text/plain;base64,aGVsbG8=")
    check(not result["ok"] and result["error"] == "attach-verify", "file assignment and composer text are not a verified chip", result)


def test_fetch(suite: Suite) -> None:
    page = suite.page("chatgpt")
    page.evaluate("""window.originalFetch=window.fetch;window.fetch=async (url,opts)=> {mock.fetchOpts=opts; if(String(url).endsWith('/huge.txt')) return new Response('x',{headers:{'Content-Length':String(16*1024*1024)}});return new Response('hello',{headers:{'Content-Type':'application/octet-stream'}});};""")
    result = api(page, "fetchFile", "/files/hello.text")
    check(result["ok"] and result["data_url"] == "data:text/plain;base64,aGVsbG8=" and result["size"] == 5, "same-origin data URL and MIME", result)
    check(page.evaluate('mock.fetchOpts.credentials') == 'include', "credentialed page fetch")
    check(api(page, "fetchFile", "https://other.test/x.txt")["error"] == "cross-origin-file", "cross-origin denied")
    check(api(page, "fetchFile", "/huge.txt")["error"] == "file-too-large", "15MB response cap")
    page.evaluate("window.fetch=window.originalFetch;mock.blob=URL.createObjectURL(new Blob(['blob hello'],{type:'text/plain'}))")
    result = api(page, "fetchFile", page.evaluate('mock.blob'))
    check(result["ok"] and result["size"] == 10, "same-origin blob download", result)


def test_assets(suite: Suite) -> None:
    page = suite.page("chatgpt", messages="")
    page.evaluate("""mockUser('files');mockAssistant('<p>Files</p><a download="report.txt" href="/files/report.txt">Download</a><a href="/files/report.txt">Duplicate</a><img width="240" height="170" alt="Result image" src="/files/plot.png"><img width="100" height="100" class="avatar" src="/avatar.png"><a href="javascript:evil()">Unsafe</a>');""")
    files = api(page, "snap")["files"]
    check(len(files) == 2 and files[0]["name"] == "report.txt" and files[1]["image"], "assets dedupe and image classification", files)
    transcript = api(page, "readChat")["messages"]
    check(len(transcript[-1]["files"]) == 2, "transcript files")


def test_chat_list_navigation(suite: Suite, platform: str) -> None:
    page = suite.page(platform)
    prefix = URLS[platform].rsplit('/', 1)[0]
    page.evaluate("""prefix=>{
      const sidebar=document.getElementById('sidebar');
      for(const [title,url] of [['Current',prefix+'/current'],['Other',prefix+'/other'],['Duplicate',prefix+'/other'],['External','https://external.test/chat/no']]) {
       const a=document.createElement('a');a.href=url;a.textContent=title;a.style.display='block';a.addEventListener('click',e=>{e.preventDefault();history.pushState({},'',a.href);});sidebar.append(a);
      }
    }""", prefix)
    chats = api(page, "listChats")["chats"]
    check(len(chats) == 2 and chats[0]["active"] and not chats[1]["active"], "chat list dedupe and active", chats)
    result = api(page, "navigate", prefix + '/other')
    check(result["ok"] and result["how"] == 'sidebar' and page.url.endswith('/other'), "SPA link navigation", result)
    check(api(page, "navigate", "javascript:alert(1)")["ok"] is False, "unsafe navigation returns JSON")


def test_transcript_limits_lazy(suite: Suite) -> None:
    page = suite.page("zai", messages="")
    page.evaluate("""for(let i=0;i<7;i++){mockUser('user '+i);mockAssistant('<p>assistant '+i+'</p>');}mockAssistant('<p>assistant 6</p>');const m=document.getElementById('messages');m.style.height='250px';m.style.overflowY='auto';m.scrollTop=m.scrollHeight;m.addEventListener('scroll',()=>{if(m.scrollTop===0&&!mock.older){mock.older=true;m.insertAdjacentHTML('afterbegin','<div class="chat-user">Earlier user</div><div class="chat-assistant"><div class="markdown-prose"><p>Earlier answer</p></div></div>');}});""")
    result = api(page, "readChat", 3)
    check(len(result["messages"]) == 3 and result["can_older"] and not result["full"], "transcript cap and adjacent dedupe", result)
    result = api(page, "loadOlder")
    check(result["messages"][0]["text"] == 'Earlier user' and page.evaluate('mock.older'), "scroll-up lazy loading", result)


def test_approval_and_pill(suite: Suite) -> None:
    page = suite.page("claude")
    result = api(page, "approval", {"id": "a1", "tool": "run_command", "summary": "<img src=x onerror=evil()>", "detail": "rm demo", "timeout": 1})
    check(result["ok"], "approval returns immediately")
    host = page.locator('[data-cb-ui="approval"]')
    check(host.get_attribute('dir') == 'rtl' and host.locator('img').count() == 0, "RTL approval text is escaped")
    page.wait_for_timeout(1400)
    check(any(e["type"] == "approval_response" and e["id"] == 'a1' and e["approved"] is False for e in api(page, "drain")["events"]), "approval timeout denies")
    api(page, "approval", {"id": "a2", "summary": "Allow?"})
    check(page.locator('[data-cb-ui="approval"] button', has_text='Approve').is_disabled(), "remote page cannot authorize local execution")
    page.locator('[data-cb-ui="approval"] button', has_text='Deny').click()
    check(any(e.get('id') == 'a2' and e.get('approved') is False for e in api(page, "drain")["events"]), "remote page can safely deny")
    check(api(page, "snap")["text"] == OLD, "approval overlay never leaks into response")
    pill = page.locator('[data-cb-ui="pill"]')
    box = pill.bounding_box()
    page.mouse.move(box['x'] + 8, box['y'] + 8)
    page.mouse.down()
    page.mouse.move(250, 230)
    page.mouse.up()
    check(pill.bounding_box()['x'] < box['x'] - 100, "pill is draggable")
    pill.locator('button', has_text='×').click()
    check(page.evaluate("localStorage.getItem('chatbridge.pill.hidden')") == '1', "hidden preference saved locally")
    page.evaluate(suite.source)
    check(not page.locator('[data-cb-ui="pill"]').is_visible(), "hidden preference survives reinjection")
    check(page.locator('[data-cb-ui="pill"]').count() == 1, "reinjection avoids duplicate controls")


def test_error_guards(suite: Suite) -> None:
    page = suite.page("generic")
    for name, args in [('send', [None]), ('upload', ['x', 'text/plain', 'not a data URL']), ('fetchFile', ['http://[bad']), ('approval', [None]), ('navigate', ['http://[bad'])]:
        result = api(page, name, *args)
        check(isinstance(result, dict) and result["ok"] is False and result.get("error"), f"{name} guarded JSON error", result)
    page.locator('[data-editor]').evaluate('el => el.remove()')
    check(api(page, "send", "hello")["error"] == 'no-input', "no-input truthful")
    check(api(page, "enter")["ok"] is False and api(page, "stop")["ok"] is False, "missing control guards")
    check(api(page, "dispose")["ok"] and page.locator('[data-cb-ui="pill"]').count() == 0, "dispose cleans timers and controls")
    check(api(page, "send", "after dispose")["error"] == 'disposed', "disposed agent cannot send")


def test_stop_during_send(suite: Suite) -> None:
    page = suite.page("deepseek")
    page.evaluate("mock.mode='drop';window.pendingSend=__CB__.send('will be stopped');setTimeout(()=>__CB__.stop(),450)")
    result = page.evaluate('window.pendingSend')
    check(not result["ok"] and result["error"] == 'stopped' and page.evaluate('mock.sent') == 1, "stop forbids PoW reinjection", result)


def test_injection_fallback(suite: Suite, editable: bool, reject: bool = False) -> None:
    page = suite.page('generic', editable=editable)
    page.evaluate("""reject => {
      document.execCommand=()=>false;
      const editor=document.querySelector('[data-editor]');
      editor.addEventListener('paste',e=>{e.preventDefault();e.stopImmediatePropagation();},true);
      if(reject) editor.addEventListener('input',()=>{'value' in editor ? editor.value='' : editor.textContent='';});
    }""", reject)
    result = api(page, 'send', 'A verified injection fallback message')
    if reject:
        check(not result['ok'] and result['error'] == 'inject-verify' and page.evaluate('mock.sent') == 0, 'failed landing cannot falsely send', result)
    else:
        expected = 'text' if editable else 'native'
        check(result['ok'] and result['how'].startswith(expected + '+'), f'{expected} verified fallback', result)


def test_nested_banner(suite: Suite) -> None:
    page = suite.page('deepseek', messages='')
    page.evaluate("""mockAssistant('<div><div>chatbridge-tool-call</div><div><pre><code>{"tool":"list_dir","args":{"path":"."}}</code></pre></div></div>');""")
    text = api(page, 'snap')['text']
    check(text.startswith('```chatbridge-tool-call\n') and text.endswith('```'), 'nested plain banner harvested', text)
    page.wait_for_timeout(1700)
    check(page.locator('[data-cb-ui="tool-chip"]').count() == 1, 'nested tool container gets neutral chip')
    check(page.locator('pre').evaluate('el=>el.getBoundingClientRect().height') == 0, 'raw payload fully collapsed')
    check(api(page, 'snap')['text'] == text, 'zero-height raw DOM remains readable')


def test_shadow_units(suite: Suite) -> None:
    page = suite.page('chatgpt', messages='')
    page.evaluate("""mockUser('Visible user before shadow');const host=document.createElement('dil-chat');document.getElementById('messages').append(host);host.attachShadow({mode:'open'}).innerHTML='<div data-content-search-unit-key="shadow:assistant"><div data-markdown-text-style><p>Assistant unit itself lives in an open shadow root.</p></div></div>';""")
    snap = api(page, 'snap')
    check(snap['count'] == 1 and 'unit itself' in snap['text'], 'composed order accepts shadow assistant after user', snap)
    messages = api(page, 'readChat')['messages']
    check([m['role'] for m in messages] == ['user', 'assistant'], 'composed transcript order', messages)


def test_wire_cap_soft_limit(suite: Suite) -> None:
    page = suite.page('zai', messages='')
    page.evaluate("mockAssistant('<p>'+ 'x'.repeat(210000) +'</p>')")
    snap = api(page, 'snap')
    check(len(snap['text']) == 200000, 'wire response cap is 200k, not old 20k')
    check(any(limit['kind'] == 'soft' for limit in snap['limits']), 'soft limit above 200k')
    page.evaluate("document.querySelector('.markdown-prose p').textContent='x'.repeat(190000)")
    check(any(limit['kind'] == 'soft' for limit in api(page, 'snap')['limits']), 'soft-limit 90% hysteresis')
    page.evaluate("document.querySelector('.markdown-prose p').textContent='x'.repeat(170000)")
    check(not api(page, 'snap')['limits'], 'soft limit clears below 90%')


def test_desktop_approval_dismiss(suite: Suite) -> None:
    page = suite.page('claude')
    api(page, 'approval', {'id': 'desktop-approved', 'summary': 'Local tool'})
    result = api(page, 'approvalDismiss', 'desktop-approved', True)
    check(result['ok'] and result['dismissed'] and page.locator('[data-cb-ui="approval"]').count() == 0, 'desktop approval closes modal immediately', result)
    check(any(e.get('id') == 'desktop-approved' and e.get('approved') is True for e in api(page, 'drain')['events']), 'desktop dismissal event')
    result = api(page, 'approvalDismiss', 'desktop-approved')
    check(result['ok'] and not result['dismissed'], 'duplicate dismissal harmless', result)


def test_shadow_tool_collapse(suite: Suite) -> None:
    page = suite.page('chatgpt', messages='')
    page.evaluate("""const unit=mockAssistant('');const host=document.createElement('dil-tool');unit.replaceChildren(host);host.attachShadow({mode:'open'}).innerHTML='<div data-markdown-text-style><div><span>chatbridge-tool-call</span><pre><code>{"tool":"list_dir","args":{"path":"."}}</code></pre></div></div>';""")
    text = api(page, 'snap')['text']
    page.wait_for_timeout(1700)
    check(page.locator('dil-tool pre').evaluate('el=>el.getBoundingClientRect().height') == 0, 'tool collapse style crosses open shadow boundary')
    check(api(page, 'snap')['text'] == text and '```chatbridge-tool-call' in text, 'shadow collapse preserves capture')
    api(page, 'dispose')
    check(page.locator('dil-tool [data-cb-ui]').count() == 0 and page.locator('dil-tool pre').get_attribute('data-cb-tool') is None, 'shadow decorations disposed without removing original code')


def cases() -> list[tuple[str, Callable[[Suite], None]]]:
    tests: list[tuple[str, Callable[[Suite], None]]] = []
    for platform in URLS:
        tests.append((f"send/{platform}", lambda s, p=platform: platform_send(s, p)))
    tests.append(("send/generic-contenteditable", lambda s: platform_send(s, 'generic', True)))
    tests.extend([
        ("chatgpt/optimistic", test_optimistic),
        ("zai/multi-unit", lambda s: test_multi(s, 'zai')),
        ("deepseek/multi-unit", lambda s: test_multi(s, 'deepseek')),
        ("markdown/walker-and-banner", test_markdown),
        ("markdown/collapse-preserves-DOM", test_banner_collapse),
        ("markdown/nested-shadow", test_shadow),
        ("generic/baseline-diff", test_generic_diff),
        ("generic/bottom-editor", test_bottom_editor),
        ("send/focused-enter-fallback", test_enter_fallback),
        ("deepseek/pow-accepted", lambda s: test_deepseek_pow(s, 'delayed')),
        ("deepseek/pow-stuck", lambda s: test_deepseek_pow(s, 'stuck')),
        ("deepseek/pow-dropped", lambda s: test_deepseek_pow(s, 'drop')),
        ("deepseek/rect-arrow-disabled", test_deepseek_controls),
        ("watcher/two-read-busy-events", test_busy_debounce),
        ("thinking/placeholder-and-expand-once", test_placeholder_think),
        ("limits/scoped-only-no-navigation", test_limits),
    ])
    for strategy in ['input', 'drag', 'paste']:
        tests.append((f"upload/{strategy}", lambda s, h=strategy: test_upload(s, h)))
    tests.extend([
        ("upload/unverified-rejected", test_upload_unverified),
        ("fetch/credentials-blob-size-origin", test_fetch),
        ("files/response-and-transcript-assets", test_assets),
        ("transcript/cap-dedupe-lazy", test_transcript_limits_lazy),
        ("controls/approval-RTL-timeout-pill", test_approval_and_pill),
        ("contract/JSON-errors-dispose", test_error_guards),
        ("send/stop-cancels-reinjection", test_stop_during_send),
        ("injection/native-setter", lambda s: test_injection_fallback(s, False)),
        ("injection/contenteditable-text", lambda s: test_injection_fallback(s, True)),
        ("injection/unverified-rejected", lambda s: test_injection_fallback(s, False, True)),
        ("markdown/nested-code-banner", test_nested_banner),
        ("markdown/composed-shadow-units", test_shadow_units),
        ("limits/wire-cap-and-hysteresis", test_wire_cap_soft_limit),
        ("controls/desktop-approval-dismiss", test_desktop_approval_dismiss),
        ("markdown/shadow-tool-collapse", test_shadow_tool_collapse),
    ])
    for platform in URLS:
        tests.append((f"navigation/{platform}", lambda s, p=platform: test_chat_list_navigation(s, p)))
    return tests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--headed', action='store_true')
    parser.add_argument('--filter', default='')
    parser.add_argument('--traceback', action='store_true')
    args = parser.parse_args()
    source = AGENT.read_text(encoding='utf-8')
    selected = [(name, test) for name, test in cases() if args.filter in name]
    if not selected:
        print('No matching tests.', file=sys.stderr)
        return 2
    failed = []
    started = time.monotonic()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        suite = Suite(browser, source)
        try:
            for name, test in selected:
                tick = time.monotonic()
                try:
                    test(suite)
                    print(f'PASS {name} ({time.monotonic()-tick:.2f}s)', flush=True)
                except Exception as exc:  # Independent cases must all run, including after failure.
                    failed.append(name)
                    print(f'FAIL {name}: {exc}', flush=True)
                    if args.traceback:
                        traceback.print_exc()
                finally:
                    suite.close()
        finally:
            browser.close()
    print(f'\n{len(selected)-len(failed)}/{len(selected)} passed; {len(failed)} failed; {time.monotonic()-started:.1f}s.', flush=True)
    if failed:
        print('Failed: ' + ', '.join(failed))
    print('Scope: synthetic DOMs only; live selector drift, trusted events, WebView2, driver capture/parser and account/network behavior require integration/manual tests.')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
