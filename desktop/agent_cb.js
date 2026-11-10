/* ChatBridge page agent. DOM only: the Python driver owns capture and tool parsing. */
(() => {
  'use strict';
  const VER = '2.50.0';
  // All site-specific selectors live here. Never use generated build-hash classes.
  const HINTS = {
    common: {
      editor: ['textarea', '[contenteditable="true"]'],
      send: ['button', '[role="button"]', 'input[type="submit"]'],
      sendNamed: ['[data-testid*="send" i]', '[aria-label*="send" i]', '[title*="send" i]', '[type="submit"]'],
      stop: ['[data-testid="stop-button"]', '#composer-stop-button', '[data-testid*="stop" i]', '#send-message-button[class*="stop" i]', 'form button[class*="stop" i]', 'button[aria-label*="stop" i]', 'button[title*="stop" i]', 'button[class*="stop" i]'],
      loading: ['.dot-flashing', '.dots-flashing', '.dot-pulse', '[class*="loading" i]', '[class*="spinner" i]', '[class*="animate-pulse" i]', '[class*="animate-bounce" i]', '[role="progressbar"]'],
      thinking: ['[class*="think" i]', '[class*="thought" i]'],
      thinkToggle: ['[aria-expanded="false"]', 'button', '[role="button"]'],
      thinkBody: ['[class*="content" i]', '[class*="body" i]'],
      unit: ['[data-message-author-role]', '[data-role="assistant"]', '[data-role="user"]', '[class~="assistant-message"]', '[class~="user-message"]'],
      body: ['[data-markdown-text-style]', '.markdown', '[class*="markdown" i]'],
      generic: ['main p', 'main div', 'main article', 'main section', 'main pre', 'main li'],
      main: ['main', '[role="main"]'],
      fileInput: ['form input[type="file"]', 'main input[type="file"]', 'input[type="file"]'],
      form: ['form', 'fieldset', '[role="form"]'],
      attachment: ['[data-testid*="attachment" i]', '[data-testid*="file" i]', '[class*="attachment" i]', '[class*="file-chip" i]', '[data-file-name]', '[class*="upload" i]'],
      notices: ['[role="dialog"]', '[role="alert"]', '[aria-modal="true"]', '[data-testid*="notice" i]', '[class*="toast" i]', '[class*="notification" i]'],
      links: ['a[href]'], images: ['img'], pre: ['pre'], code: ['code'],
      language: ['[data-language]', '[class*="language-"]'],
      tableRows: ['tr'], tableCells: ['th', 'td'], listItems: ['li'],
      skip: ['script', 'style', 'button', 'svg', 'input', 'select', 'textarea', 'noscript', '[aria-hidden="true"]', '[hidden]', '.sr-only', '[class*="sr-only"]', '[data-cb-ui]'],
      roots: ['*'], rect: ['svg rect'], arrow: ['svg path']
    },
    chatgpt: {
      host: /(^|\.)chatgpt\.com$/, home: 'https://chatgpt.com/', chat: /^\/c\//,
      editor: ['div[contenteditable="true"]#prompt-textarea', 'form div[contenteditable="true"]', 'form textarea[data-id]', 'textarea[data-id="root"]', '#prompt-textarea'],
      send: ['button[data-testid="send-button"]', 'button[aria-label*="send" i]', 'form button[type="submit"]'],
      stop: ['button[data-testid="stop-button"]', 'button[aria-label*="stop" i]'],
      unit: ['[data-content-search-unit-key$=":assistant"]', '[data-turn-key]'],
      transcript: ['[data-content-search-unit-key]', '[data-turn-key]', '[data-message-author-role]'],
      body: ['[data-markdown-text-style]', '.markdown', '[data-message-author-role="assistant"]'],
      users: ['[data-content-search-unit-key$=":user"]', '[data-message-author-role="user"]'],
      assistantRole: ['[data-message-author-role="assistant"]'],
      isAssistant: el => /:assistant$/.test(el.getAttribute('data-content-search-unit-key') || '') || el.getAttribute('data-message-author-role') === 'assistant' || has(el, HINTS.chatgpt.assistantRole),
      busy: () => !!findStop(), stableMs: 1100, captureTimeoutMs: 180000
    },
    claude: {
      host: /(^|\.)claude\.ai$/, home: 'https://claude.ai/', chat: /^\/chat\//,
      editor: ['div.ProseMirror[contenteditable="true"]', 'div[contenteditable="true"].font-claude-message', 'fieldset div[contenteditable="true"]'],
      send: ['button[aria-label="Send Message"]', 'button[aria-label*="send" i]', 'button[data-testid="send-button"]'],
      stop: ['button[aria-label*="stop" i]'],
      unit: ['[data-testid="assistant-message"]', '.claude-message', '[data-testid="conversation-turn"]', '[data-testid="transcript-row"][data-perf-row="assistant"]'],
      transcript: ['[data-testid="transcript-row"]', '[data-testid="user-message"], [data-testid="assistant-message"]', '[data-testid="conversation-turn"]'],
      users: ['[data-testid="transcript-row"][data-perf-row="human"]', '[data-testid="user-message"]'],
      body: ['.font-claude-message', '[class*="markdown" i]', '.claude-message'],
      isAssistant: el => el.getAttribute('data-perf-row') === 'assistant' || el.getAttribute('data-testid') === 'assistant-message' || el.classList.contains('claude-message') || (el.getAttribute('data-testid') === 'conversation-turn' && !has(el, HINTS.claude.users)),
      busy: () => !!findStop(), pasteFirst: true, stableMs: 1100, captureTimeoutMs: 180000
    },
    zai: {
      host: /(^|\.)z\.ai$/, home: 'https://chat.z.ai/', chat: /^\/c\//,
      editor: ['textarea#chat-input', 'textarea[placeholder*="message" i]', 'textarea'],
      send: ['#send-message-button', 'button.sendMessageButton', 'form button[type="submit"]'],
      stop: ['#send-message-button[class*="stop" i]', '#send-message-button[aria-label*="stop" i]', 'button[aria-label*="stop" i]'],
      unit: ['.chat-user, .chat-assistant'], transcript: ['.chat-user, .chat-assistant'],
      users: ['.chat-user'], body: ['.markdown-prose', '.chat-assistant'],
      loading: ['.chat-assistant .dot', '#response-content-container .dot', '.dot-flashing', '.dots-flashing', '.dot-pulse', '[class*="spinner" i]', '[class*="pulse" i]', '[class*="animate-bounce" i]', 'main .dot'],
      isAssistant: el => el.classList.contains('chat-assistant'),
      busy: () => !!findStop() || anyVisible(HINTS.zai.loading), multi: true, stableMs: 1500, captureTimeoutMs: 300000, beforeSendMs: 90000
    },
    deepseek: {
      host: /(^|\.)deepseek\.com$/, home: 'https://chat.deepseek.com/', chat: /^\/a\/chat\/s\//,
      editor: ['textarea[placeholder*="deepseek" i]', 'textarea[name="search"]', 'form textarea', 'textarea', 'div[contenteditable="true"]', '[role="textbox"]'],
      send: ['div[role="button"].ds-button--primary', 'button[type="submit"]', 'button[aria-label*="send" i]', '[role="button"][aria-label*="send" i]'],
      stop: ['div[role="button"].ds-button--primary', 'button[aria-label*="stop" i]', '[role="button"][aria-label*="stop" i]'],
      unit: ['.ds-message', '[data-testid*="message" i]', '[class*="message" i]'],
      transcript: ['.ds-message', '[data-testid*="message" i]', '[class*="message" i]'],
      body: ['.ds-markdown.ds-assistant-message-main-content', '.ds-markdown', '[data-message-author-role="assistant"]', '[class*="assistant" i] [class*="markdown" i]'],
      assistantRole: ['.ds-markdown.ds-assistant-message-main-content', '[data-message-author-role="assistant"]', '[class*="assistant" i]'], users: [],
      isAssistant: el => has(el, HINTS.deepseek.assistantRole) || /assistant|ai|markdown/i.test(String(el.className || '')),
      busy: () => { const b = deepseekControl(); return !!b && square(b); },
      multi: true, stableMs: 1500, captureTimeoutMs: 300000, powGraceMs: 2200
    },
    gemini: {
      host: /(^|\.)gemini\.google\.com$/, home: 'https://gemini.google.com/app', chat: /^\/app\/[\w-]+/,
      editor: ['div.ql-editor[contenteditable="true"]', 'rich-textarea div[contenteditable="true"]', 'div[contenteditable="true"]'],
      send: ['button.send-button', 'button[aria-label*="send" i]', 'button[mattooltip*="send" i]', 'div[aria-label*="send" i]'],
      stop: ['button[aria-label*="stop" i]'],
      unit: ['model-response', 'message-content', '.model-response-text', '.conversation-container'],
      transcript: ['user-query, model-response', 'message-content', '.conversation-container'],
      users: ['user-query', '[data-role="user"]'], body: ['message-content', '.model-response-text'],
      isAssistant: el => el.tagName === 'MODEL-RESPONSE' || el.tagName === 'MESSAGE-CONTENT' || el.classList.contains('model-response-text') || (el.classList.contains('conversation-container') && !has(el, HINTS.gemini.users)),
      busy: () => !!findStop(), stableMs: 1100, captureTimeoutMs: 180000
    },
    generic: {
      home: '', chat: /\/(?:c|chat|conversation|session)s?\//,
      editor: [], send: [], stop: [], unit: [], transcript: [], users: [], body: [],
      isAssistant: el => el.getAttribute('data-message-author-role') === 'assistant' || el.getAttribute('data-role') === 'assistant' || el.classList.contains('assistant-message'),
      busy: () => !!findStop(), stableMs: 1100, captureTimeoutMs: 180000
    }
  };
  try { if (window.__CB__ && typeof window.__CB__.dispose === 'function') window.__CB__.dispose(); } catch (_) { /* reinjection is safe */ }
  const platform = Object.keys(HINTS).find(k => HINTS[k].host && HINTS[k].host.test(location.hostname)) || 'generic';
  const hint = HINTS[platform];
  // Per-host selectors from the standalone platform_hints.json. They are
  // prepended so an explicit site config wins over the generic guesses.
  const _custom = (window.__CB_HOST_HINTS__ && typeof window.__CB_HOST_HINTS__ === 'object') ? window.__CB_HOST_HINTS__ : null;
  if (_custom) for (const _k of ['editor','send','stop','unit','users','body','transcript','loading']) {
    const _list = Array.isArray(_custom[_k]) ? _custom[_k].filter(x => typeof x === 'string' && x.trim()) : [];
    if (_list.length) hint[_k] = _list.concat(hint[_k] || []);
  }
  const MAX_BYTES = 15 * 1024 * 1024;
  const MAX_TEXT = 200000;
  const events = [];
  const timers = new Set();
  const approvals = new Map();
  const expandedThink = new WeakSet();
  const collapsed = new WeakSet();
  const decorations = [];
  const shadowStyles = new Map();
  let disposed = false, sending = false, stopEpoch = 0, fileSettledAt = 0;
  // Last text ChatBridge injected. Generic sites have no author attributes, so
  // this is how reading() tells our own message apart from the model reply.
  let lastInjected = '';
  let genericBase = new Map(), genericArmed = false;
  let observer = null, pill = null, style = null, busyCandidate = null, busyReads = 0, busyPublished = null;
  let lastLimitAt = 0, softLimit = false, lastMutationSweep = 0;
  const limitSeen = new Map();
  const error = e => ({ok: false, error: String(e && e.message || e || 'unknown-error')});
  const safe = fn => (...args) => { try { return fn(...args); } catch (e) { return error(e); } };
  const safeAsync = fn => async (...args) => { try { return await fn(...args); } catch (e) { return error(e); } };
  function trace(stage, fields = {}) {
    // Diagnostic metadata only: never include the user's prompt or response.
    emit({type: 'browser_log', text: `[agent:${platform}] ${stage} ${JSON.stringify(fields)}`});
  }
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  function repeat(fn, ms) { const id = setInterval(() => { if (!disposed) { try { fn(); } catch (_) { /* watcher must not break the page */ } } }, ms); timers.add(id); return id; }
  function emit(event) { if (disposed) return; events.push({platform, page_url: location.href, ...event}); if (events.length > 200) events.shift(); }
  function roots(root = document) {
    const out = [root];
    for (let i = 0; i < out.length; i++) {
      let all = []; try { all = out[i].querySelectorAll(HINTS.common.roots[0]); } catch (_) { /* non-DOM root */ }
      for (const el of all) if (el.shadowRoot && !el.hasAttribute('data-cb-ui')) out.push(el.shadowRoot);
    }
    return out;
  }
  function query(selector, root = document) {
    const found = [];
    for (const r of roots(root)) { try { if (r.nodeType === 1 && r.matches(selector)) found.push(r); found.push(...r.querySelectorAll(selector)); } catch (_) { /* unsupported selectors are hints */ } }
    return [...new Set(found)].filter(el => !owned(el));
  }
  function all(selectors, root = document) { return [...new Set((selectors || []).flatMap(s => query(s, root)))]; }
  function matches(el, selectors) { return !!el && (selectors || []).some(s => { try { return el.matches(s); } catch (_) { return false; } }); }
  function has(el, selectors) { return matches(el, selectors) || all(selectors, el).length > 0; }
  function parent(el) { return el && (el.parentElement || (el.getRootNode && el.getRootNode().host)); }
  function owned(el) { for (let p = el; p; p = parent(p)) if (p.nodeType === 1 && p.hasAttribute('data-cb-ui')) return true; return false; }
  function visible(el) {
    if (!el || el.nodeType !== 1 || owned(el)) return false;
    for (let p = el; p; p = parent(p)) {
      if (p.hidden || p.getAttribute('aria-hidden') === 'true') return false;
      const css = getComputedStyle(p); if (css.display === 'none' || css.visibility === 'hidden' || css.visibility === 'collapse') return false;
    }
    const r = el.getBoundingClientRect();
    return r.width >= 6 && r.height >= 6 || (!r.width && !r.height && el.offsetWidth >= 6 && el.offsetHeight >= 6);
  }
  function enabled(el) { return visible(el) && !el.disabled && el.getAttribute('aria-disabled') !== 'true' && !/(?:^|[\s_-])disabled(?:[\s_-]|$)/i.test(el.className && String(el.className)); }
  function anyVisible(selectors) { return all(selectors).some(visible); }
  function choose(selectors, {last = false, allowDisabled = false, root = document} = {}) {
    for (const selector of selectors || []) { const items = query(selector, root).filter(allowDisabled ? visible : enabled); if (items.length) return {el: last ? items[items.length - 1] : items[0], selector}; }
    return {el: null, selector: null};
  }
  function bottom(items) { return items.sort((a, b) => a.getBoundingClientRect().bottom - b.getBoundingClientRect().bottom).pop() || null; }
  function findEditor() {
    const specific = choose(hint.editor); if (specific.el) return specific;
    return {el: bottom(all(HINTS.common.editor).filter(enabled)), selector: 'generic:lowest-editor'};
  }
  function editorText(el) { return el ? String('value' in el ? el.value : deepText(el, false)) : ''; }
  function carries(el, text) { return editorText(el).replace(/\r/g, '').includes(text.replace(/\r/g, '').slice(0, 60)); }
  function square(el) { return all(HINTS.common.rect, el).some(r => { const box = r.getBoundingClientRect(); return box.width > 0 && box.height > 0; }); }
  function deepseekControl() {
    let p = findEditor().el;
    for (let i = 0; p && i < 8; i++, p = parent(p)) { const list = all(hint.send, p).filter(visible); if (list.length) return list[list.length - 1]; }
    const list = all(hint.send).filter(visible); return list[list.length - 1] || null;
  }
  function isStop(el) { return !!el && (platform === 'deepseek' ? square(el) : matches(el, [...hint.stop, ...HINTS.common.stop]) || /stop/i.test([el.getAttribute('aria-label'), el.getAttribute('title'), el.className].join(' '))); }
  function findStop() {
    if (platform === 'deepseek') { const b = deepseekControl(); return b && square(b) ? b : null; }
    return choose([...hint.stop, ...HINTS.common.stop], {allowDisabled: true, last: true}).el;
  }
  function findSend() {
    if (platform === 'deepseek') { const b = deepseekControl(); return {el: b && enabled(b) && !square(b) ? b : null, selector: hint.send[0]}; }
    for (const s of hint.send) { const list = query(s).filter(el => enabled(el) && !isStop(el)); if (list.length) return {el: list[list.length - 1], selector: s}; }
    let p = findEditor().el;
    for (let i = 0; p && i < 6; i++, p = parent(p)) {
      const items = all(HINTS.common.send, p).filter(el => enabled(el) && !isStop(el) && !/attach|upload|voice|microphone|search|settings|copy|download/i.test([el.getAttribute('aria-label'), el.getAttribute('title'), el.textContent].join(' ')));
      const named = items.filter(el => matches(el, HINTS.common.sendNamed) || /^(?:send|submit|➤|↑|→)$/i.test(el.textContent.trim()));
      if (named.length || items.length) return {el: bottom(named.length ? named : items), selector: 'generic:near-editor'};
    }
    return {el: null, selector: null};
  }
  function focused(el) { let active = document.activeElement; while (active && active.shadowRoot && active.shadowRoot.activeElement) active = active.shadowRoot.activeElement; return active === el || !!active && el.contains(active); }
  function focus(el) { if (!el) return false; try { el.focus({preventScroll: true}); } catch (_) { el.focus(); } return focused(el); }
  function children(node) { return node.shadowRoot ? [...node.shadowRoot.childNodes] : [...node.childNodes]; }
  function skip(el, thinking = true) {
    if (matches(el, HINTS.common.skip)) return true;
    if (thinking && matches(el, HINTS.common.thinking) && !/^(?:PRE|CODE)$/.test(el.tagName)) return true;
    // Collapsed tool code remains in the DOM and must remain readable.
    if (!el.hasAttribute('data-cb-tool')) { const css = getComputedStyle(el); if (css.display === 'none' || css.visibility === 'hidden') return true; }
    return false;
  }
  function deepText(node, thinking = true) {
    if (!node) return '';
    if (node.nodeType === 3) return node.nodeValue || '';
    if (node.nodeType !== 1 && node.nodeType !== 11) return '';
    if (node.nodeType === 1 && skip(node, thinking)) return '';
    const text = children(node).map(n => deepText(n, thinking)).join('');
    return node.nodeType === 1 && /^(P|DIV|LI|PRE|H[1-6]|BLOCKQUOTE|TR|SECTION|ARTICLE)$/.test(node.tagName) ? text + '\n' : text;
  }
  function clean(text) {
    return String(text || '').replace(/<ds_safety>[\s\S]*?(?:<\/ds_safety>\s*(?:Safe\b)?|$)/gi, '')
      .replace(/ChatGPT said:\s*/gi, '')
      .split('\n').filter(line => !/^\s*(?:Thinking[.…]*|Thought for \d+(?:\.\d+)?\s*(?:seconds?|s)[.…]*|Searching[.…]*|Generating[.…]*|در حال فکر[.…]*|思考中[.…]*)\s*$/i.test(line)).join('\n')
      .replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
  }
  function escapeInline(s) { return String(s).replace(/([\\`*\[\]])/g, '\\$1'); }
  function safeURL(url) { try { const u = new URL(url, location.href); return /^(https?:|blob:|data:|mailto:)$/.test(u.protocol) ? u.href : ''; } catch (_) { return ''; } }
  function rawCode(node) { if (node.nodeType === 3) return node.nodeValue || ''; if (node.nodeType !== 1 && node.nodeType !== 11) return ''; if (node.nodeType === 1 && matches(node, HINTS.common.skip)) return ''; return children(node).map(rawCode).join(''); }
  function explicitLanguage(pre) {
    const nodes = [pre, ...all(HINTS.common.code, pre), ...all(HINTS.common.language, pre)];
    for (const el of nodes) {
      const attr = el.getAttribute('data-language'); if (attr && /^[\w+.#-]{1,64}$/.test(attr)) return attr;
      const match = String(el.className || '').match(/(?:^|\s)language-([\w+.#-]+)/); if (match) return match[1];
    }
    // A stable data-language on the immediate code wrapper is explicit too.
    const p = parent(pre); return p && /^[\w+.#-]{1,64}$/.test(p.getAttribute('data-language') || '') ? p.getAttribute('data-language') : '';
  }
  function overheadText(node, pre) {
    if (node === pre) return '';
    if (node.nodeType === 3) return node.nodeValue || '';
    if (node.nodeType !== 1 && node.nodeType !== 11 || node.nodeType === 1 && matches(node, HINTS.common.skip)) return '';
    return children(node).map(child => overheadText(child, pre)).join(' ');
  }
  function banner(pre, wrapper = parent(pre)) {
    if (!wrapper || wrapper === document.body) return '';
    const text = overheadText(wrapper, pre).trim();
    if (text.length > 80) return '';
    const cb = text.match(/\bchatbridge(?:-tool-(?:call|result))?\b/i); if (cb) return cb[0].toLowerCase();
    const stripped = text.replace(/\b(copy(?: code)?|download(?: code)?|copied|code)\b/gi, '').trim();
    return /^[\w+.#-]{1,32}$/.test(stripped) ? stripped : '';
  }
  function sniff(code) {
    if (/^\s*<\?php\b/.test(code)) return 'php';
    if (/^\s*<!doctype html\b/i.test(code)) return 'html';
    if (/^\s*(?:def \w+\(|from [\w.]+ import |import (?:os|sys|json|re)\b)/m.test(code)) return 'python';
    if (/^#!.*\b(?:ba|z|k)?sh\b/.test(code)) return 'bash';
    if (/^\s*(?:SELECT .+ FROM |CREATE TABLE |INSERT INTO )/im.test(code)) return 'sql';
    return '';
  }
  function codeBlock(pre, wrapper) {
    const c = all(HINTS.common.code, pre)[0] || pre;
    const text = rawCode(c).replace(/^\n|\n$/g, '');
    let label = banner(pre, wrapper);
    if (!label) for (let p = parent(pre), i = 0; p && i < 3; p = parent(p), i++) { if (all(HINTS.common.pre, p).length !== 1) break; label = banner(pre, p); if (label) break; }
    const language = explicitLanguage(pre) || label || sniff(text);
    const runs = text.match(/`+/g) || []; const fence = '`'.repeat(Math.max(3, ...runs.map(s => s.length + 1)));
    return '\n\n' + fence + language + '\n' + text + '\n' + fence + '\n\n';
  }
  function markdown(node, depth = 0) {
    if (!node || depth > 120) return '';
    if (node.nodeType === 3) return escapeInline(node.nodeValue || '');
    if (node.nodeType !== 1 && node.nodeType !== 11) return '';
    if (node.nodeType === 1 && skip(node)) return '';
    if (node.nodeType === 11) return children(node).map(n => markdown(n, depth + 1)).join('');
    const tag = node.tagName;
    if (tag === 'PRE') return codeBlock(node);
    // Harvest the banner before discarding short code-container overhead.
    if (/^(DIV|SECTION|FIGURE)$/.test(tag)) {
      const pres = all(HINTS.common.pre, node);
      if (pres.length === 1) {
        const overhead = overheadText(node, pres[0]).trim();
        const prose = [...node.children].some(n => /^(P|H[1-6]|UL|OL|BLOCKQUOTE)$/.test(n.tagName) && !contains(n, pres[0]));
        if (!prose && overhead.length <= 80) return codeBlock(pres[0], node);
      }
    }
    if (tag === 'BR') return '\n';
    if (tag === 'HR') return '\n\n---\n\n';
    if (tag === 'IMG') return node.getAttribute('alt') || '';
    if (tag === 'CODE') { const text = rawCode(node); const runs = text.match(/`+/g) || []; const tick = '`'.repeat(Math.max(1, ...runs.map(s => s.length + 1))); return tick + (/^`|`$/.test(text) ? ' ' : '') + text + (/^`|`$/.test(text) ? ' ' : '') + tick; }
    const content = children(node).map(n => markdown(n, depth + 1)).join('');
    if (/^H[1-6]$/.test(tag)) return '\n\n' + '#'.repeat(Number(tag[1])) + ' ' + content.trim() + '\n\n';
    if (tag === 'STRONG' || tag === 'B') return '**' + content + '**';
    if (tag === 'EM' || tag === 'I') return '*' + content + '*';
    if (tag === 'DEL' || tag === 'S') return '~~' + content + '~~';
    if (tag === 'A') { const href = safeURL(node.getAttribute('href')); return href ? '[' + content.trim() + '](' + href.replace(/\)/g, '%29') + ')' : content; }
    if (tag === 'BLOCKQUOTE') return '\n\n' + content.trim().split('\n').map(l => '> ' + l).join('\n') + '\n\n';
    if (tag === 'UL' || tag === 'OL') {
      const start = Number(node.getAttribute('start')) || 1;
      const lines = [...node.children].filter(n => n.tagName === 'LI').map((li, i) => {
        const text = children(li).map(n => markdown(n, depth + 1)).join('').trim();
        return (tag === 'OL' ? (start + i) + '. ' : '- ') + text.replace(/\n/g, '\n  ');
      });
      return '\n\n' + lines.join('\n') + '\n\n';
    }
    if (tag === 'TABLE') {
      const rows = all(HINTS.common.tableRows, node).filter(r => !skip(r)).map(r => [...r.children].filter(c => matches(c, HINTS.common.tableCells)).map(c => children(c).map(n => markdown(n, depth + 1)).join('').trim().replace(/\|/g, '\\|').replace(/\n/g, '<br>'))).filter(r => r.length);
      if (!rows.length) return '';
      const width = Math.max(...rows.map(r => r.length));
      const row = r => '| ' + Array.from({length: width}, (_, i) => r[i] || '').join(' | ') + ' |';
      return '\n\n' + row(rows[0]) + '\n' + row(Array(width).fill('---')) + '\n' + rows.slice(1).map(row).join('\n') + '\n\n';
    }
    if (/^(P|DIV|ARTICLE|SECTION|FIGURE|LI|DL|DT|DD)$/.test(tag)) return '\n\n' + content.trim() + '\n\n';
    return content;
  }
  function bodyText(unit) {
    for (const selector of hint.body.length ? hint.body : HINTS.common.body) {
      const bodies = query(selector, unit).filter(el => !skip(el));
      if (bodies.length) {
        const top = bodies.filter(el => !bodies.some(other => other !== el && contains(other, el)));
        const text = clean(top.map(el => markdown(el)).join('\n\n')); if (text) return text;
      }
    }
    // The walker is a non-mutating overhead-stripped view, including open shadow roots.
    return clean(markdown(unit)) || clean(deepText(unit));
  }
  function contains(a, b) { for (let p = b; p; p = parent(p)) if (p === a) return true; return false; }
  function position(a, b) {
    let p = a.compareDocumentPosition(b);
    if (!(p & Node.DOCUMENT_POSITION_DISCONNECTED)) return p;
    // Compare shadow hosts in the composed document, not implementation-defined
    // ordering bits on nodes in different roots.
    const chain = el => { const list = [el]; let root = el.getRootNode(); while (root.host) { list.push(root.host); root = root.host.getRootNode(); } return list; };
    const ac = chain(a), bc = chain(b);
    for (const x of ac) for (const y of bc) {
      if (x === y) continue;
      p = x.compareDocumentPosition(y); if (!(p & Node.DOCUMENT_POSITION_DISCONNECTED)) return p;
    }
    return 0;
  }
  function order(items) { return [...new Set(items)].sort((a, b) => { if (a === b) return 0; const p = position(a, b); return p & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : p & Node.DOCUMENT_POSITION_PRECEDING ? 1 : 0; }); }
  function nonNested(items) { return order(items).filter(el => !items.some(other => other !== el && contains(other, el))); }
  function role(el) {
    if (hint.isAssistant(el)) return 'assistant';
    if (matches(el, hint.users) || has(el, hint.users) || /:user$/.test(el.getAttribute('data-content-search-unit-key') || '') || /^(user|human)$/.test(el.getAttribute('data-message-author-role') || el.getAttribute('data-role') || el.getAttribute('data-perf-row') || '') || el.tagName === 'USER-QUERY' || el.classList.contains('user-message')) return 'user';
    return platform === 'deepseek' || platform === 'zai' ? 'user' : null;
  }
  function units(transcript = false) {
    const selectors = transcript ? hint.transcript : hint.unit;
    if (platform === 'zai' || platform === 'deepseek') return nonNested(all(selectors));
    if (transcript && platform === 'claude') return nonNested(all(selectors).filter(el => role(el)));
    for (const s of selectors) {
      let items = query(s);
      if (!transcript) items = items.filter(hint.isAssistant);
      else items = items.filter(el => role(el));
      if (items.length) {
        if (platform === 'chatgpt' && /search-unit/.test(s)) {
          const keys = new Set(); items = items.filter(el => { const key = el.getAttribute('data-content-search-unit-key'); if (keys.has(key)) return false; keys.add(key); return true; });
        }
        return nonNested(items);
      }
    }
    return nonNested(all(HINTS.common.unit).filter(el => transcript ? role(el) || HINTS.generic.isAssistant(el) : HINTS.generic.isAssistant(el)));
  }
  function genericBlocks() {
    const editor = findEditor().el;
    const items = all(HINTS.common.generic).filter(el => !owned(el) && !skip(el) && el !== editor && !(editor && contains(el, editor)) && visible(el) && clean(deepText(el)).length >= 40);
    // Prefer leaf-ish content over wrappers containing several old/new messages.
    return order(items.filter(el => !items.some(child => child !== el && contains(el, child))));
  }
  function sentByUs(t) {
    if (!lastInjected) return false;
    const a = String(t || '').trim().replace(/\s+/g, ' ');
    const b = String(lastInjected || '').trim().replace(/\s+/g, ' ');
    if (!a || !b) return false;
    if (/\[ChatBridge\s*[·\-]\s*automatic\s+tool-result/i.test(a)) return true;
    if (a === b) return true;
    if (a.length >= 80 && b.length >= 80) {
      const n = Math.min(120, a.length, b.length);
      if (a.slice(0, n) === b.slice(0, n)) return true;
    }
    return false;
  }
  function reading() {
    const allUnits = units(false), assistants = allUnits.filter(el => hint.isAssistant(el) || HINTS.generic.isAssistant(el));
    let current = assistants;
    const userUnits = units(true).filter(el => role(el) === 'user');
    const extraUsers = all(hint.users || []);
    const users = order([...userUnits, ...extraUsers]);
    if (users.length) { const lastUser = users[users.length - 1]; current = assistants.filter(el => !!(position(lastUser, el) & Node.DOCUMENT_POSITION_FOLLOWING)); }
    if (!hint.multi && current.length > 1) current = [current[current.length - 1]];
    if (!allUnits.length && !assistants.length) {
      const blocks = genericBlocks().filter(el => !sentByUs(bodyText(el)));
      const changed = genericArmed ? blocks.filter(el => !genericBase.has(el) || bodyText(el) !== genericBase.get(el)) : blocks.slice(-1);
      return {count: blocks.length, text: clean(changed.map(bodyText).join('\n\n')).slice(0, MAX_TEXT), units: changed, all: blocks, users: users.length, generic: true};
    }
    return {count: assistants.length, text: clean(current.map(bodyText).join('\n\n')).slice(0, MAX_TEXT), units: current, all: allUnits, users: users.length, generic: false};
  }
  function thinking() {
    const candidates = all(HINTS.common.thinking).filter(el => visible(el) && !matches(el, HINTS.common.skip) && !/^(PRE|CODE)$/.test(el.tagName));
    if (platform === 'zai') {
      let clicks = 0;
      for (const el of candidates) {
        if (expandedThink.has(el) || clicks >= 3) continue;
        const toggles = all(HINTS.common.thinkToggle, el);
        const toggle = toggles.find(b => b.getAttribute('aria-expanded') === 'false') || (all(HINTS.common.thinkBody, el).some(b => !visible(b)) ? toggles.find(enabled) : null);
        if (toggle && enabled(toggle)) { expandedThink.add(el); toggle.click(); clicks++; }
      }
    }
    const el = candidates.find(e => !candidates.some(p => p !== e && contains(p, e)));
    if (!el) return {think: '', think_active: false};
    const raw = deepText(el, false).trim();
    const label = [el.getAttribute('aria-label') || '', ...children(el).slice(0, 3).map(n => n.nodeType === 3 ? n.nodeValue : n.textContent)].join(' ').trim();
    const completed = /Thought for\s+\d+|thought\s+\d+|思考了|فکر.*\d+/i.test(label);
    return {think: clean(raw).slice(0, 12000), think_active: !completed && /(?:^|\s)(?:thinking|searching|generating)(?:[.…\s]|$)|در حال فکر|思考中/i.test(label)};
  }
  function busy() { return !!hint.busy() || anyVisible(HINTS.common.loading); }
  function assets(unitList, transcript = false) {
    const result = [], seen = new Set();
    const add = (el, image) => {
      const url = safeURL(image ? el.currentSrc || el.getAttribute('src') : el.getAttribute('href')); if (!url || seen.has(url)) return;
      seen.add(url); let name = image ? el.getAttribute('alt') : el.getAttribute('download') || clean(deepText(el, false));
      if (!name) { try { name = decodeURIComponent(new URL(url).pathname.split('/').pop()) || (image ? 'image' : 'file'); } catch (_) { name = 'file'; } }
      result.push({name: name.slice(0, 180), url, image: !!image});
    };
    const fileExt = /\.(?:txt|text|md|pdf|csv|json|zip|tar|gz|docx?|xlsx?|pptx?|py|js|html|png|jpe?g|gif|webp|svg|mp3|mp4)(?:[?#]|$)/i;
    for (const original of unitList) {
      let unit = original;
      if (platform === 'chatgpt') { for (let p = original, i = 0; p && i < 5; p = parent(p), i++) if (p.hasAttribute('data-turn-key')) { unit = p; break; } }
      for (const link of all(HINTS.common.links, unit)) { const href = link.getAttribute('href') || ''; if (link.hasAttribute('download') || fileExt.test(href) || /\/mnt\/data\/|\/files\/|^blob:/.test(href)) add(link, /\.(png|jpe?g|gif|webp|svg)(?:[?#]|$)/i.test(href)); }
      for (const img of all(HINTS.common.images, unit)) {
        if (/avatar|profile|icon/i.test([img.className, img.getAttribute('alt')].join(' '))) continue;
        const w = Number(img.getAttribute('width')) || img.naturalWidth || img.getBoundingClientRect().width;
        const h = Number(img.getAttribute('height')) || img.naturalHeight || img.getBoundingClientRect().height;
        const src = img.currentSrc || img.getAttribute('src') || '';
        if (transcript ? w >= 96 || h >= 96 || !img.hasAttribute('width') && !img.hasAttribute('height') : w >= 220 && h >= 160 || fileExt.test(src)) add(img, true);
      }
    }
    return result.slice(0, transcript ? 6 : 8);
  }
  const strongLimit = /you(?:'|’)ve (?:reached|hit)(?: our| the| your)? (?:usage |message )?limit|you(?:'|’)re out of free (?:credits|messages)|conversation (?:is )?too long[\s\S]*start a new chat|usage cap|reached the maximum conversation length|you(?:'|’)re using the free version of ChatGPT|upgrade for advanced models|محدودیت طول گفتگو/i;
  function limits(read = reading()) {
    const out = [];
    for (const el of all(HINTS.common.notices).filter(visible)) { const text = clean(deepText(el, false)); if (text.length <= 600 && strongLimit.test(text)) out.push({kind: 'hard', where: matches(el, HINTS.common.notices.slice(0, 3)) ? 'dialog' : 'page-notice', snippet: text.slice(0, 600)}); }
    const last = read.units[read.units.length - 1];
    if (last) { const text = bodyText(last); if (strongLimit.test(text)) out.push({kind: 'hard', where: 'assistant', snippet: (text.match(strongLimit) || [text])[0].slice(0, 600)}); }
    if (platform === 'chatgpt') {
      const tail = units(true).slice(-3);
      for (const el of tail) { const text = clean(deepText(el, false)); const found = text.match(/you(?:'|’)re using the free version of ChatGPT|upgrade for advanced models/i); if (found) out.push({kind: 'hard', where: 'page-notice', snippet: found[0]}); }
    }
    const transcriptUnits = units(true);
    const total = (transcriptUnits.length ? transcriptUnits : genericBlocks()).reduce((n, el) => n + deepText(el).length, 0);
    if (total > MAX_TEXT) softLimit = true; else if (total < MAX_TEXT * 0.9) softLimit = false;
    if (softLimit) out.push({kind: 'soft', where: 'assistant', snippet: 'Conversation exceeds 200,000 characters.'});
    return out.filter((item, i) => out.findIndex(other => other.kind === item.kind && other.snippet === item.snippet) === i);
  }
  function scanLimits() {
    const now = Date.now(); if (now - lastLimitAt < 5000) return; lastLimitAt = now;
    for (const item of limits()) { const key = item.kind + item.where + item.snippet; if (now - (limitSeen.get(key) || 0) >= 60000) { limitSeen.set(key, now); emit({type: 'limit_reached', ...item}); } }
  }
  function collapseTools() {
    for (const pre of all(HINTS.common.pre)) {
      if (collapsed.has(pre)) continue;
      let wrapper = parent(pre), lang = explicitLanguage(pre) || banner(pre);
      if (!/^chatbridge/.test(lang)) for (let p = wrapper, i = 0; p && i < 3; p = parent(p), i++) { if (all(HINTS.common.pre, p).length !== 1) break; const label = banner(pre, p); if (/^chatbridge/.test(label)) { lang = label; wrapper = p; break; } }
      if (!/^chatbridge(?:-tool-(?:call|result))?$/i.test(lang) && !/chatbridge-tool-(?:call|result)|[<＜][^\n]*DSML[^\n]*tool_calls/.test(rawCode(pre))) continue;
      collapsed.add(pre); pre.setAttribute('data-cb-tool', 'collapsed');
      const root = pre.getRootNode();
      if (root.host && style && !shadowStyles.has(root)) { const local = style.cloneNode(true); root.append(local); shadowStyles.set(root, local); }
      const labels = wrapper ? [...wrapper.children].filter(el => !contains(el, pre) && !owned(el)) : [];
      for (const el of labels) el.setAttribute('data-cb-tool-label', 'collapsed');
      const chip = document.createElement('button'); chip.setAttribute('data-cb-ui', 'tool-chip'); chip.type = 'button'; chip.textContent = 'ChatBridge · tool block'; chip.title = 'Expand or collapse the original tool block';
      chip.addEventListener('click', () => { const state = pre.getAttribute('data-cb-tool') === 'collapsed' ? 'expanded' : 'collapsed'; pre.setAttribute('data-cb-tool', state); for (const el of labels) el.setAttribute('data-cb-tool-label', state); });
      pre.before(chip);
      decorations.push({pre, labels, chip});
    }
  }
  function watchBusy() {
    const value = busy();
    if (value === busyCandidate) busyReads++; else { busyCandidate = value; busyReads = 1; }
    if (busyReads >= 2 && value !== busyPublished) { busyPublished = value; emit({type: 'platform_busy', busy: value}); }
    if (pill) { const dot = pill.firstElementChild; if (dot) { dot.textContent = value ? '●' : '○'; dot.title = value ? 'Generating' : 'Ready'; dot.style.color = value ? '#ffb454' : '#76dba8'; } }
    scanLimits(); collapseTools();
  }
  function probe() {
    const e = findEditor(), s = findSend(), stop = findStop();
    const counts = {};
    for (const selector of [...hint.editor, ...hint.send, ...hint.stop, ...hint.unit, ...hint.body]) counts[selector] = query(selector).length;
    return {ok: true, platform, editor: !!e.el, editor_selector: e.selector, send: !!s.el, send_selector: s.selector, stop: !!stop, ready: !!e.el, counts};
  }
  async function waitReady(timeout = 30000) {
    const until = Date.now() + Math.max(1000, Math.min(120000, Number(timeout) || 30000));
    let last = probe();
    while (!disposed && Date.now() < until) {
      last = probe();
      // Send controls are commonly disabled while the composer is empty. The
      // send ladder must inject text first, then discover the enabled button.
      if (last.editor) return {...last, ready: true};
      await sleep(300);
    }
    return {...last, ok: false, error: 'page-not-ready', ready: false};
  }
  function baseline() {
    const read = reading();
    genericBase = new Map(genericBlocks().map(el => [el, bodyText(el)])); genericArmed = true;
    return {ok: true, count: read.count, last: read.text, text: read.text, user_count: read.users, url: location.href};
  }
  function snap() {
    const read = reading(), think = thinking(), isBusy = busy();
    const editor = findEditor().el;
    const stage = think.think_active ? 'thinking' : read.text && isBusy ? 'writing' : isBusy ? 'loading' : 'waiting';
    return {ok: true, count: read.count, text: read.text, busy: isBusy, stage, ...think, url: location.href, title: document.title, ready: !!editor, composer: editorText(editor), files: assets(read.units), limits: limits(read), probe: probe(), generic: read.generic};
  }
  function selectAll(el) {
    if ('value' in el) { el.setSelectionRange(0, el.value.length); return; }
    const range = document.createRange(); range.selectNodeContents(el);
    const selection = el.getRootNode().getSelection ? el.getRootNode().getSelection() : window.getSelection();
    if (selection) { selection.removeAllRanges(); selection.addRange(range); }
  }
  function inputEvent(el, type, data) { let event; try { event = new InputEvent(type, {bubbles: true, composed: true, inputType: 'insertText', data}); } catch (_) { event = new Event(type, {bubbles: true, composed: true}); } el.dispatchEvent(event); }
  async function inject(el, text) {
    const strategies = hint.pasteFirst ? ['paste', 'exec', 'native', 'text'] : ['exec', 'paste', 'native', 'text'];
    for (const how of strategies) {
      if (!focus(el)) continue;
      try {
        selectAll(el);
        if (how === 'exec') document.execCommand('insertText', false, text);
        if (how === 'paste') { const data = new DataTransfer(); data.setData('text/plain', text); const ev = new ClipboardEvent('paste', {bubbles: true, cancelable: true, composed: true, clipboardData: data}); el.dispatchEvent(ev); }
        if (how === 'native') {
          if (!/^(TEXTAREA|INPUT)$/.test(el.tagName)) continue;
          const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          const setter = Object.getOwnPropertyDescriptor(proto, 'value').set; setter.call(el, text); inputEvent(el, 'input', text);
        }
        if (how === 'text') { if ('value' in el) continue; el.textContent = text; inputEvent(el, 'beforeinput', text); inputEvent(el, 'input', text); }
        await sleep(80);
        if (carries(el, text)) return {ok: true, how};
      } catch (_) { /* continue down the verified injection ladder */ }
    }
    return {ok: false, error: 'inject-verify'};
  }
  function pressEnter(el) {
    if (!focus(el)) return false;
    for (const type of ['keydown', 'keypress', 'keyup']) {
      const event = new KeyboardEvent(type, {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true, composed: true});
      el.dispatchEvent(event);
    }
    return true;
  }
  async function settleFile() { const remaining = fileSettledAt - Date.now(); if (remaining > 0) await sleep(remaining); }
  function evidence(before, el) {
    const r = reading();
    if (r.users > before.users || r.count > before.count || r.text && r.text !== before.text || findStop()) return 'accepted';
    if (!editorText(el).trim()) return platform === 'deepseek' && !busy() ? 'dropped' : 'accepted';
    return 'stuck';
  }
  async function verify(before, el, epoch) {
    await sleep(160);
    if (disposed || epoch !== stopEpoch) return 'stopped';
    let verdict = evidence(before, el);
    if (platform === 'deepseek' && verdict === 'dropped') {
      const until = Date.now() + hint.powGraceMs;
      while (Date.now() < until) { await sleep(180); if (disposed || epoch !== stopEpoch) return 'stopped'; verdict = evidence(before, el); if (verdict === 'accepted') return verdict; }
    }
    return verdict;
  }
  async function send(text) {
    if (disposed) return {ok: false, error: 'disposed'};
    if (typeof text !== 'string' || !text.trim()) return {ok: false, error: 'empty-message'};
    if (sending) return {ok: false, error: 'send-in-progress', verdict: 'stuck'};
    sending = true;
    const epoch = stopEpoch;
    trace('send-start', {length: text.length, editor: !!findEditor().el, send: !!findSend().el});
    try {
      // Never inject a queued result into a generating composer.
      const idleUntil = Date.now() + (hint.beforeSendMs || 45000);
      while (busy()) {
        if (Date.now() >= idleUntil) return {ok: false, error: 'platform-busy', reason: 'send-failed', verdict: 'stuck'};
        if (disposed || epoch !== stopEpoch) return {ok: false, error: 'stopped', verdict: 'stuck'};
        await sleep(250);
      }
      let el = findEditor().el; if (!el) { trace('no-editor'); return {ok: false, error: 'no-input', reason: 'no-input', verdict: 'stuck'}; }
      await settleFile();
      const before = reading();
      // Remember exactly what we sent so the reply reader can drop it.
      lastInjected = text;
      let injected = await inject(el, text);
      trace('injection', {ok: !!injected.ok, how: injected.how || null, composerLength: editorText(el).length});
      if (!injected.ok) return {...injected, reason: 'send-failed', verdict: 'stuck', probe: probe()};
      let verdict = 'stuck', how = injected.how;
      for (let round = 1; round <= 3; round++) {
        if (disposed || epoch !== stopEpoch) return {ok: false, error: 'stopped', verdict: 'stuck'};
        el = findEditor().el || el;
        if (round > 1 && !carries(el, text)) {
          // Reinject only after the PoW grace window, never after a user stop.
          if (busy()) { verdict = evidence(before, el); if (verdict === 'accepted') return {ok: true, how, verdict, round}; return {ok: false, error: 'platform-busy', verdict: 'stuck'}; }
          injected = await inject(el, text); if (!injected.ok) return {...injected, verdict: 'stuck'};
        }
        await settleFile(); focus(el);
        let button = findSend().el;
        trace('send-control', {round, found: !!button, enabled: !!button && enabled(button), stop: !!button && isStop(button), selector: findSend().selector || null, composerLength: editorText(el).length});
        if (button && focus(el) && enabled(button) && !isStop(button)) { button.click(); how = injected.how + '+click'; }
        verdict = await verify(before, el, epoch);
        trace('click-verdict', {round, verdict, count: reading().count, textLength: reading().text.length});
        if (verdict === 'accepted') return {ok: true, how, verdict, round, probe: probe()};
        if (verdict === 'stopped') return {ok: false, error: 'stopped', verdict: 'stuck'};
        if (verdict === 'dropped') continue;
        if (carries(el, text) && pressEnter(el)) how = injected.how + '+enter';
        trace('enter-fallback', {round, used: how.endsWith('+enter'), composerLength: editorText(el).length});
        verdict = await verify(before, el, epoch);
        trace('enter-verdict', {round, verdict, count: reading().count, textLength: reading().text.length});
        if (verdict === 'accepted') return {ok: true, how, verdict, round, probe: probe()};
        if (verdict === 'stopped') return {ok: false, error: 'stopped', verdict: 'stuck'};
        if (verdict === 'dropped') continue;
        const until = Date.now() + 4000;
        do {
          if (disposed || epoch !== stopEpoch) return {ok: false, error: 'stopped', verdict: 'stuck'};
          verdict = evidence(before, el); if (verdict === 'accepted') return {ok: true, how, verdict, round};
          button = findSend().el; if (button) break;
          await sleep(160);
        } while (Date.now() < until);
        if (button && focus(el) && enabled(button) && !isStop(button)) { button.click(); how = injected.how + '+retry-click'; verdict = await verify(before, el, epoch); }
        if (verdict === 'accepted') return {ok: true, how, verdict, round};
        if (verdict === 'stopped') return {ok: false, error: 'stopped', verdict: 'stuck'};
      }
      trace('send-failed', {how, verdict, probe: probe()});
      return {ok: false, how, verdict, error: verdict === 'dropped' ? 'send-dropped' : 'send-failed', reason: verdict === 'dropped' ? 'send-dropped' : 'send-failed', probe: probe()};
    } finally { sending = false; }
  }
  async function typeText(text) {
    if (disposed) return {ok: false, error: 'disposed'};
    if (typeof text !== 'string' || !text.trim()) return {ok: false, error: 'empty-message'};
    const el = findEditor().el; if (!el) return {ok: false, error: 'no-input'};
    const injected = await inject(el, text);
    trace('type', {ok: !!injected.ok, how: injected.how || null});
    return injected;
  }
  async function submit() {
    if (disposed) return {ok: false, error: 'disposed'};
    const epoch = stopEpoch;
    const el = findEditor().el; if (!el) return {ok: false, error: 'no-input'};
    await settleFile();
    const before = reading();
    const until = Date.now() + 20000;
    let button = null;
    while (Date.now() < until) {
      if (disposed || epoch !== stopEpoch) return {ok: false, error: 'stopped'};
      focus(el);
      button = findSend().el;
      if (button && enabled(button) && !isStop(button)) break;
      await sleep(250);
    }
    if (button && enabled(button) && !isStop(button)) { button.click(); }
    let verdict = await verify(before, el, epoch);
    if (verdict !== 'accepted' && verdict !== 'stopped' && focus(el)) { pressEnter(el); verdict = await verify(before, el, epoch); }
    trace('submit', {verdict: verdict, found: !!button});
    return {ok: verdict === 'accepted', verdict: verdict, probe: probe()};
  }
  function mimeFor(name, supplied) {
    const ext = name.toLowerCase().split('.').pop();
    const known = {txt: 'text/plain', text: 'text/plain', md: 'text/markdown', csv: 'text/csv', json: 'application/json', html: 'text/html', py: 'text/plain', js: 'text/javascript', pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif', zip: 'application/zip'};
    return supplied && supplied !== 'application/octet-stream' ? supplied : known[ext] || supplied || 'application/octet-stream';
  }
  function decodeFile(name, mime, dataURL) {
    if (typeof dataURL !== 'string' || dataURL.length > MAX_BYTES * 1.4 + 1024) throw new Error('file-too-large-or-invalid');
    const match = dataURL.match(/^data:([^;,]*)(;base64)?,([\s\S]*)$/); if (!match) throw new Error('invalid-data-url');
    const raw = match[2] ? atob(match[3]) : decodeURIComponent(match[3]);
    const bytes = match[2] ? Uint8Array.from(raw, c => c.charCodeAt(0)) : new TextEncoder().encode(raw);
    if (bytes.length > MAX_BYTES) throw new Error('file-too-large');
    return new File([bytes], name, {type: mimeFor(name, mime || match[1])});
  }
  function composerScope(el) {
    let p = el;
    for (let i = 0; p && i < 8; i++, p = parent(p)) if (matches(p, HINTS.common.form)) return p;
    return parent(parent(el)) || parent(el) || el;
  }
  function chipNodes(scope, name) {
    const base = name.replace(/\.[^.]+$/, '').toLowerCase();
    const candidates = [...all(HINTS.common.attachment, scope), ...query(HINTS.common.roots[0], scope)];
    return candidates.filter(el => visible(el) && !matches(el, HINTS.common.editor) && !has(el, HINTS.common.editor) && !matches(el, HINTS.common.fileInput) && !/^(BUTTON|SVG)$/.test(el.tagName)).filter(el => {
      const text = [deepText(el, false), el.getAttribute('data-file-name') || ''].join(' ').trim().toLowerCase();
      return text.length <= 600 && (text.includes(name.toLowerCase()) || base.length >= 3 && text.includes(base));
    });
  }
  async function verifyChip(el, name, before) {
    const until = Date.now() + 4200;
    do { const found = chipNodes(composerScope(el), name).find(node => !before.has(node)); if (found) return true; await sleep(300); } while (Date.now() < until && !disposed);
    return false;
  }
  async function upload(name, mime, dataURL) {
    if (disposed) return {ok: false, error: 'disposed'};
    if (typeof name !== 'string' || !name.trim()) return {ok: false, error: 'invalid-file-name'};
    const el = findEditor().el; if (!el) return {ok: false, error: 'no-input'};
    const file = decodeFile(name, mime, dataURL), dt = new DataTransfer(); dt.items.add(file);
    const before = new Set(chipNodes(composerScope(el), name));
    // If this file is already attached (e.g. a retry), never add it again.
    if (chipNodes(composerScope(el), name).length > 0) { fileSettledAt = Date.now() + 1500; return {ok: true, how: 'already-attached', name, size: file.size, mime: file.type}; }
    // Prefer the canonical file input. Only fall back to drag/paste when no
    // input exists, so the same file is never attached by multiple methods.
    const hasInput = all(HINTS.common.fileInput, composerScope(el)).some(e => !e.disabled) || all(HINTS.common.fileInput).some(e => !e.disabled);
    for (const how of (hasInput ? ['input'] : ['drag', 'paste'])) {
      // Another strategy already attached it; do not duplicate.
      if (chipNodes(composerScope(el), name).length > 0) { fileSettledAt = Date.now() + 1500; return {ok: true, how: how + '+existing', name, size: file.size, mime: file.type}; }
      try {
        focus(el);
        if (how === 'input') { const input = all(HINTS.common.fileInput, composerScope(el)).find(e => !e.disabled) || all(HINTS.common.fileInput).find(e => !e.disabled); if (!input) continue; input.files = dt.files; input.dispatchEvent(new Event('input', {bubbles: true, composed: true})); input.dispatchEvent(new Event('change', {bubbles: true, composed: true})); }
        if (how === 'drag') for (const type of ['dragenter', 'dragover', 'drop']) el.dispatchEvent(new DragEvent(type, {bubbles: true, cancelable: true, composed: true, dataTransfer: dt}));
        if (how === 'paste') el.dispatchEvent(new ClipboardEvent('paste', {bubbles: true, cancelable: true, composed: true, clipboardData: dt}));
        fileSettledAt = Date.now() + 2200;
        if (await verifyChip(el, name, before)) { fileSettledAt = Date.now() + 2200; return {ok: true, how, name, size: file.size, mime: file.type}; }
      } catch (_) { /* next upload strategy */ }
    }
    return {ok: false, error: 'attach-verify', size: file.size};
  }
  async function fetchFile(url) {
    const u = new URL(String(url), location.href);
    const blobOrigin = u.protocol === 'blob:' ? new URL(u.pathname).origin : null;
    if (!(u.protocol === 'blob:' && blobOrigin === location.origin || /^https?:$/.test(u.protocol) && u.origin === location.origin)) return {ok: false, error: 'cross-origin-file'};
    const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(u.href, {credentials: 'include', redirect: 'error', signal: controller.signal});
      if (!response.ok) return {ok: false, error: 'http-' + response.status};
      if (response.url && new URL(response.url).origin !== location.origin) return {ok: false, error: 'cross-origin-redirect'};
      if (Number(response.headers.get('content-length')) > MAX_BYTES) return {ok: false, error: 'file-too-large'};
      const chunks = []; let size = 0;
      if (response.body && response.body.getReader) {
        const reader = response.body.getReader();
        while (true) { const {done, value} = await reader.read(); if (done) break; size += value.byteLength; if (size > MAX_BYTES) { await reader.cancel(); return {ok: false, error: 'file-too-large'}; } chunks.push(value); }
      } else { const value = new Uint8Array(await response.arrayBuffer()); size = value.byteLength; if (size > MAX_BYTES) return {ok: false, error: 'file-too-large'}; chunks.push(value); }
      const name = u.pathname.split('/').pop() || 'file';
      const blob = new Blob(chunks, {type: mimeFor(name, response.headers.get('content-type') || '')});
      const dataURL = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = () => reject(new Error('file-read-error')); reader.readAsDataURL(blob); });
      return {ok: true, data_url: dataURL, size, mime: blob.type};
    } finally { clearTimeout(timeout); }
  }
  function sameConversation(a, b) { try { const x = new URL(a, location.href), y = new URL(b, location.href); return x.origin === y.origin && x.pathname.replace(/\/$/, '').split('/').pop() === y.pathname.replace(/\/$/, '').split('/').pop(); } catch (_) { return false; } }
  function listChats() {
    const chats = [], seen = new Set();
    for (const el of all(HINTS.common.links).filter(visible)) {
      const url = safeURL(el.getAttribute('href')); if (!url) continue;
      const u = new URL(url); if (u.origin !== location.origin || !hint.chat.test(u.pathname) || seen.has(url)) continue;
      seen.add(url); chats.push({title: clean(deepText(el, false)).slice(0, 200) || u.pathname.split('/').pop(), url, active: el.hasAttribute('aria-current') && el.getAttribute('aria-current') !== 'false' || /(?:^|\s)(?:active|selected)(?:\s|$)/.test(String(el.className)) || sameConversation(url, location.href)});
      if (chats.length >= 60) break;
    }
    return {ok: true, chats};
  }
  function scroller() {
    const first = units(true)[0] || all(HINTS.common.main)[0];
    for (let p = first, i = 0; p && i < 14; p = parent(p), i++) if (p.scrollHeight > p.clientHeight + 80 && p.clientHeight > 0 && /auto|scroll/.test(getComputedStyle(p).overflowY)) return p;
    return document.scrollingElement || document.documentElement;
  }
  function transcript(limit) {
    let list = units(true);
    if (!list.length) list = genericBlocks();
    const messages = [];
    for (const el of list) {
      const r = role(el) || (HINTS.generic.isAssistant(el) ? 'assistant' : 'assistant');
      const text = r === 'assistant' ? bodyText(el) : clean(deepText(el, false));
      const files = assets([el], true); if (!text && !files.length) continue;
      const prev = messages[messages.length - 1]; if (prev && prev.role === r && prev.text === text) { prev.files = [...new Map([...(prev.files || []), ...files].map(f => [f.url, f])).values()].slice(0, 6); continue; }
      messages.push({role: r, text: text.slice(0, MAX_TEXT), ...(files.length ? {files} : {})});
    }
    const scroll = scroller(), capped = messages.length > limit;
    return {ok: true, url: location.href, messages: messages.slice(-limit), can_older: capped || scroll.scrollTop > 20, full: !capped && scroll.scrollTop <= 20};
  }
  async function readChat(limit = 40) {
    limit = Math.min(200, Math.max(1, Number(limit) || 40));
    let result = transcript(limit);
    for (let i = 0; i < 2 && !result.messages.length && !disposed; i++) { await sleep(2200); const next = transcript(limit); if (next.messages.reduce((n, m) => n + m.text.length + (m.files || []).length * 100, 0) > result.messages.reduce((n, m) => n + m.text.length + (m.files || []).length * 100, 0)) result = next; }
    return result;
  }
  async function loadOlder() {
    const scroll = scroller(); let previous = '';
    for (let i = 0; i < 8 && !disposed; i++) {
      scroll.scrollTop = 0; scroll.dispatchEvent(new Event('scroll', {bubbles: true})); await sleep(350);
      const list = units(true); const signature = list.length + ':' + (list[0] ? deepText(list[0]).slice(0, 100) : '');
      if (signature === previous) break; previous = signature;
    }
    return readChat(200);
  }
  async function navigate(url) {
    const u = new URL(String(url), location.href);
    if (!/^https?:$/.test(u.protocol) || u.origin !== location.origin) return {ok: false, error: 'unsafe-navigation'};
    const link = all(HINTS.common.links).find(el => visible(el) && sameConversation(el.href, u.href));
    if (link) { link.click(); await sleep(1400); genericArmed = false; return {ok: true, how: 'sidebar', url: location.href}; }
    location.assign(u.href); return {ok: true, how: 'location', url: u.href};
  }
  function approval(payload) {
    if (disposed) return {ok: false, error: 'disposed'};
    if (!payload || typeof payload.id !== 'string' || !payload.id) return {ok: false, error: 'invalid-approval'};
    if (approvals.has(payload.id)) return {ok: true, id: payload.id, duplicate: true};
    const host = document.createElement('div'); host.setAttribute('data-cb-ui', 'approval'); host.dir = 'rtl'; host.setAttribute('role', 'dialog'); host.setAttribute('aria-modal', 'true');
    Object.assign(host.style, {position: 'fixed', inset: '0', zIndex: '2147483647', display: 'grid', placeItems: 'center', background: '#0009', font: '14px system-ui'});
    const card = document.createElement('div'); Object.assign(card.style, {background: '#17202c', color: '#f0f4ff', border: '1px solid #607080', borderRadius: '14px', padding: '22px', maxWidth: '600px', width: 'min(85vw,600px)', maxHeight: '80vh', overflow: 'auto'});
    const heading = document.createElement('h3'); heading.textContent = 'ChatBridge · Approval required';
    const summary = document.createElement('p'); summary.textContent = String(payload.summary || payload.tool || 'Local operation');
    const detail = document.createElement('pre'); detail.textContent = String(payload.detail || '').slice(0, 20000); detail.style.whiteSpace = 'pre-wrap';
    const countdown = document.createElement('p');
    const allow = document.createElement('button'), deny = document.createElement('button'); allow.textContent = 'Approve in the desktop app'; deny.textContent = 'Deny';
    allow.disabled = true;
    allow.title = 'Only the trusted desktop UI can authorize local operations.';
    for (const b of [allow, deny]) { b.type = 'button'; Object.assign(b.style, {padding: '9px 18px', margin: '5px', cursor: 'pointer'}); }
    card.append(heading, summary, detail, countdown, allow, deny); host.append(card); (document.body || document.documentElement).append(host);
    const seconds = Math.max(1, Math.min(120, Number(payload.timeout || payload.approval_timeout) || 120));
    const expires = Date.now() + seconds * 1000;
    let id;
    const finish = approved => { if (!approvals.has(payload.id)) return; clearInterval(id); timers.delete(id); host.remove(); approvals.delete(payload.id); emit({type: 'approval_response', id: payload.id, approved: !!approved}); };
    deny.addEventListener('click', () => finish(false));
    id = repeat(() => { const left = Math.max(0, Math.ceil((expires - Date.now()) / 1000)); countdown.textContent = 'Auto-deny in ' + left + ' seconds'; if (!left) finish(false); }, 250);
    countdown.textContent = 'Auto-deny in ' + seconds + ' seconds'; approvals.set(payload.id, {host, finish}); deny.focus();
    return {ok: true, id: payload.id};
  }
  function makePill() {
    style = document.createElement('style'); style.setAttribute('data-cb-ui', 'style');
    style.textContent = '[data-cb-tool="collapsed"],[data-cb-tool-label="collapsed"]{display:block!important;height:0!important;max-height:0!important;min-height:0!important;padding:0!important;margin:0!important;border:0!important;overflow:hidden!important;opacity:0!important}[data-cb-ui="tool-chip"]{display:inline-block!important;font:11px system-ui!important;padding:4px 8px!important;border:1px solid #71849b!important;border-radius:6px!important;background:#1b2635!important;color:#d1dcec!important;cursor:pointer!important}';
    (document.head || document.documentElement).append(style);
    pill = document.createElement('div'); pill.setAttribute('data-cb-ui', 'pill'); pill.setAttribute('aria-label', 'ChatBridge page controls');
    Object.assign(pill.style, {position: 'fixed', right: '14px', bottom: '14px', zIndex: '2147483646', display: 'flex', gap: '5px', alignItems: 'center', border: '1px solid #71849b', borderRadius: '20px', padding: '5px 9px', color: '#dce6f4', background: '#182331', font: '12px system-ui', touchAction: 'none', cursor: 'move'});
    const dot = document.createElement('span'); dot.textContent = '○'; pill.append(dot);
    const btn = (text, title, action) => { const b = document.createElement('button'); b.type = 'button'; b.textContent = text; b.title = title; Object.assign(b.style, {background: 'transparent', color: 'inherit', border: '0', cursor: 'pointer'}); b.addEventListener('click', () => { try { action(); } catch (_) { /* controls never break the agent */ } }); pill.append(b); };
    btn('⟳', 'Refresh agent probe', () => { emit({type: 'agent_probe', probe: probe()}); watchBusy(); });
    btn('⌂', 'Go to platform home (new chat)', () => { if (hint.home) location.assign(hint.home); });
    btn('×', 'Hide controls', () => { pill.style.display = 'none'; try { localStorage.setItem('chatbridge.pill.hidden', '1'); } catch (_) { /* unavailable storage */ } });
    try { if (localStorage.getItem('chatbridge.pill.hidden') === '1') pill.style.display = 'none'; } catch (_) { /* private storage */ }
    let drag = null;
    pill.addEventListener('pointerdown', e => { if (e.target.tagName === 'BUTTON') return; const r = pill.getBoundingClientRect(); drag = {x: e.clientX - r.left, y: e.clientY - r.top}; pill.setPointerCapture(e.pointerId); e.preventDefault(); });
    pill.addEventListener('pointermove', e => { if (!drag) return; pill.style.left = Math.max(0, Math.min(innerWidth - pill.offsetWidth, e.clientX - drag.x)) + 'px'; pill.style.top = Math.max(0, Math.min(innerHeight - pill.offsetHeight, e.clientY - drag.y)) + 'px'; pill.style.right = 'auto'; pill.style.bottom = 'auto'; });
    pill.addEventListener('pointerup', () => { drag = null; }); pill.addEventListener('pointercancel', () => { drag = null; });
    (document.body || document.documentElement).append(pill);
  }
  function dispose() {
    disposed = true; stopEpoch++;
    for (const id of timers) clearInterval(id); timers.clear(); if (observer) observer.disconnect();
    for (const {host} of approvals.values()) host.remove(); approvals.clear();
    if (pill) pill.remove(); if (style) style.remove();
    // Remove only our decoration, never the page's original code content.
    for (const {pre, labels, chip} of decorations) { pre.removeAttribute('data-cb-tool'); for (const el of labels) el.removeAttribute('data-cb-tool-label'); chip.remove(); }
    decorations.length = 0;
    for (const local of shadowStyles.values()) local.remove(); shadowStyles.clear();
    return {ok: true};
  }
  // Stable CSS path: prefer ids/roles/aria over hashed build classes which
  // change on every deploy.
  function cssPath(el) {
    if (!el || el.nodeType !== 1) return '';
    const parts = []; let node = el;
    while (node && node.nodeType === 1 && parts.length < 5) {
      if (node.id) { const sel = '#' + CSS.escape(node.id); if (document.querySelectorAll(sel).length === 1) { parts.unshift(sel); break; } }
      let part = node.tagName.toLowerCase();
      const role = node.getAttribute('role'); if (role) part += '[role="' + role + '"]';
      const aria = node.getAttribute('aria-label'); if (aria) part += '[aria-label="' + aria.replace(/"/g, '\\"') + '"]';
      const sibs = node.parentElement ? Array.from(node.parentElement.children).filter(x => x.tagName === node.tagName) : [];
      if (sibs.length > 1) part += ':nth-of-type(' + (sibs.indexOf(node) + 1) + ')';
      parts.unshift(part); node = node.parentElement;
    }
    return parts.join(' > ');
  }
  function shown(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect(); if (r.width <= 0 || r.height <= 0) return false;
    const css = getComputedStyle(el); return css.display !== 'none' && css.visibility !== 'hidden';
  }
  // Element picker: the user clicks the real control instead of us guessing.
  // Result is delivered as a picker_pick event so the caller never blocks.
  let picker = null;
  function pickerStop() {
    if (!picker) return false;
    document.removeEventListener('mousemove', picker.move, true);
    document.removeEventListener('click', picker.click, true);
    document.removeEventListener('keydown', picker.key, true);
    picker.box.remove(); picker.label.remove(); picker = null;
    return true;
  }
  function pickerStart(mode) {
    pickerStop();
    const box = document.createElement('div');
    box.setAttribute('data-cb-ui', 'picker'); box.hidden = true;
    box.style.cssText = 'position:fixed;pointer-events:none;z-index:2147483647;border:2px solid #a49aff;background:rgba(164,154,255,.14);border-radius:4px';
    const label = document.createElement('div');
    label.setAttribute('data-cb-ui', 'picker'); label.hidden = true;
    label.style.cssText = 'position:fixed;pointer-events:none;z-index:2147483647;background:#111218;color:#e5e5ec;font:11px monospace;padding:2px 6px;border-radius:4px;border:1px solid #2b2d39;max-width:60vw;overflow:hidden;white-space:nowrap;text-overflow:ellipsis';
    document.documentElement.append(box, label);
    let current = null;
    const move = e => {
      const el = document.elementFromPoint(e.clientX, e.clientY);
      if (!el || el === box || el === label || (el.closest && el.closest('[data-cb-ui]'))) return;
      current = el;
      const r = el.getBoundingClientRect();
      box.hidden = false; label.hidden = false;
      box.style.left = r.left + 'px'; box.style.top = r.top + 'px';
      box.style.width = r.width + 'px'; box.style.height = r.height + 'px';
      label.style.left = r.left + 'px'; label.style.top = Math.max(0, r.top - 22) + 'px';
      label.textContent = el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + ' · ' + Math.round(r.width) + 'x' + Math.round(r.height);
    };
    const click = e => {
      if (!current) return;
      e.preventDefault(); e.stopPropagation(); if (e.stopImmediatePropagation) e.stopImmediatePropagation();
      const el = current, path = cssPath(el);
      const info = {ok: true, mode, path, tag: el.tagName.toLowerCase(),
                    role: el.getAttribute('role') || '', text: String(el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60)};
      pickerStop(); emit({type: 'picker_pick', ...info});
    };
    const key = e => { if (e.key === 'Escape') { const m = mode; pickerStop(); emit({type: 'picker_pick', ok: false, mode: m, error: 'cancelled'}); } };
    document.addEventListener('mousemove', move, true);
    document.addEventListener('click', click, true);
    document.addEventListener('keydown', key, true);
    picker = {box, label, move, click, key};
    return {ok: true, mode};
  }
  // Structural probe only: never types into the user's composer.
  function detect() {
    const editors = [];
    for (const sel of ['textarea', '[contenteditable="true"]', '[role="textbox"]', 'input[type="text"]']) {
      for (const el of document.querySelectorAll(sel)) {
        if (!shown(el)) continue;
        const path = cssPath(el); if (path && !editors.some(x => x.path === path)) editors.push({path, tag: el.tagName.toLowerCase(), placeholder: el.getAttribute('placeholder') || ''});
      }
    }
    const editorEl = (editors[0] && document.querySelector(editors[0].path)) || findEditor().el;
    const scope = editorEl ? (editorEl.closest('form') || editorEl.parentElement || document.body) : document.body;
    const sends = [];
    for (const btn of scope.querySelectorAll('button, [role="button"], input[type="submit"]')) {
      if (!shown(btn)) continue;
      const label = [btn.getAttribute('aria-label'), btn.getAttribute('title'), btn.getAttribute('data-testid'), btn.textContent].filter(Boolean).join(' ').toLowerCase();
      let score = 0;
      if (/send|submit/.test(label)) score += 5;
      if (btn.type === 'submit') score += 3;
      if (!score) continue;
      sends.push({path: cssPath(btn), score, label: label.slice(0, 40)});
    }
    sends.sort((a, b) => b.score - a.score);
    return {ok: true, host: location.hostname, editors: editors.slice(0, 8), sends: sends.slice(0, 8)};
  }
  window.__CB__ = {
    ping: safe(() => 'pong'),
    meta: safe(() => ({ok: true, version: VER, platform, url: location.href, title: document.title, ready: !!findEditor().el, stable_ms: hint.stableMs, capture_timeout_ms: hint.captureTimeoutMs})),
    probe: safe(probe), waitReady: safeAsync(waitReady), baseline: safe(baseline), snap: safe(snap), send: safeAsync(send), detect: safe(detect),
    enter: safe(() => { const el = findEditor().el; return el && pressEnter(el) ? {ok: true, how: 'enter'} : {ok: false, error: 'no-input-or-focus'}; }),
    stop: safe(() => { stopEpoch++; const el = findStop() || (platform === 'zai' && busy() ? choose(hint.send, {allowDisabled: true}).el : null); if (el && enabled(el)) { el.click(); return {ok: true, how: 'click'}; } return {ok: false, error: 'no-stop', how: 'capture-cancelled'}; }),
    type: safeAsync(typeText), submit: safeAsync(submit), upload: safeAsync(upload), fetchFile: safeAsync(fetchFile), listChats: safe(listChats), readChat: safeAsync(readChat), loadOlder: safeAsync(loadOlder), navigate: safeAsync(navigate), approval: safe(approval),
    approvalDismiss: safe((id, approved = false) => { const pending = approvals.get(id); if (pending) pending.finish(approved); return {ok: true, id, dismissed: !!pending}; }),
    drain: safe(() => ({ok: true, events: events.splice(0)})), dispose: safe(dispose),
    pick: safe(pickerStart), pickCancel: safe(() => { const was = pickerStop(); return {ok: true, cancelled: was}; })
  };
  try {
    makePill(); repeat(watchBusy, 1500); repeat(scanLimits, 5000);
    observer = new MutationObserver(() => { const now = Date.now(); if (now - lastMutationSweep >= 5000) { lastMutationSweep = now; scanLimits(); collapseTools(); } });
    observer.observe(document.documentElement, {childList: true, subtree: true, characterData: true});
    collapseTools(); emit({type: 'agent_probe', probe: probe()});
  } catch (e) { emit({type: 'agent_error', error: String(e.message || e)}); }
  return VER;
})();
