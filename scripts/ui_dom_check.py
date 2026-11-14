#!/usr/bin/env python3
"""Static ChatBridge UI acceptance pins. No framework or browser dependency."""
from __future__ import annotations
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / 'desktop' / 'ui'


class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = {}
        self.tags = []
        self.categories = set()
        self.tabs = set()
        self.translations = set()
        self.radios = 0

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        self.tags.append(tag)
        if 'id' in attrs:
            assert attrs['id'] not in self.ids, f"Duplicate id: {attrs['id']}"
            self.ids[attrs['id']] = (tag, attrs)
        self.radios += tag == 'input' and attrs.get('type') == 'radio'
        if 'data-category' in attrs:
            self.categories.add(attrs['data-category'])
        if 'data-tab' in attrs:
            self.tabs.add(attrs['data-tab'])
        for key in ('data-i18n', 'data-i18n-placeholder'):
            if key in attrs:
                self.translations.add(attrs[key])


def main():
    html = (UI / 'index.html').read_text()
    js = (UI / 'app.js').read_text()
    css = (UI / 'style.css').read_text()
    doc = Document()
    doc.feed(html)
    required = {
        'header', 'ibOpenBtn', 'connectionChip', 'modelSelect', 'projectTitle',
        'sidebar', 'sidebarToggle', 'fullAccessSwitch', 'accessWarning', 'chatList',
        'chatPanel', 'chatStream', 'approvalHost', 'composerForm', 'composerInput',
        'sendBtn', 'attachBtn', 'attachmentInput', 'attachmentHost', 'rightBlock',
        'rightSplitter', 'browserSplitter', 'ibDock', 'ibDockEmpty', 'ibDockOpen',
        'bbLog', 'browserUrl', 'fileTree', 'fileFilter', 'fileEditor', 'editorSaveBtn',
        'editorDirty', 'lineNumbers', 'terminalOutput', 'terminalKillBtn',
        'terminalRerunBtn', 'terminalSendBtn', 'gitChanges', 'gitDiff', 'confirmModal',
        'settingsModal', 'browserSettings', 'agentRulesList', 'agentRulesMaster',
        'addRuleBtn', 'resetRulesBtn', 'rulesPreview', 'rulesPreviewBtn',
    }
    assert not required - doc.ids.keys(), f'Missing pins: {required - doc.ids.keys()}'
    assert 'hidden' not in doc.ids['ibOpenBtn'][1], 'Header browser button is gated'
    assert doc.radios == 0, 'Radio controls are forbidden'
    assert 'iframe' not in doc.tags, 'Embedded third-party frames are forbidden'
    assert doc.categories == {'general', 'appearance', 'models', 'internal-browser', 'provider', 'agent-rules'}
    assert doc.tabs == {'browser', 'files', 'terminal', 'git', 'file'}
    assert '2.60.0' in html and '<html lang="en" dir="ltr"' in html
    assert not re.search(r'browser_mode|chrome\.|extension/', html + js, re.I)
    assert not re.search(r'\.innerHTML\s*=|insertAdjacentHTML|document\.write\(|\beval\(', js)
    assert '__cbIbDockRect' in js and '__cbOpenInternalBrowser' in js
    assert 'ResizeObserver' in js and 'ibrowser_fit' in js
    assert '(innerWidth-pr.right)<=pr.left' in js.replace(' ', '')
    assert 'br.right-e.clientX' in js and 'stripToolFences' in js
    assert 'operation-row' in js and 'markdown' in js and 'appendAnsi' in js
    assert all(f'data-theme="{theme}"' in css for theme in ('graphite', 'nord', 'forest', 'light', 'sepia'))
    assert all(f'data-font-size="{size}"' in css for size in ('small', 'large', 'extra-large'))
    catalogs = {}
    for locale in ('en', 'fa'):
        catalogs[locale] = json.loads((ROOT / 'desktop' / 'translations' / f'{locale}.json').read_text())
        missing = doc.translations - catalogs[locale].keys()
        assert not missing, f'{locale}: Missing translations {missing}'
    assert catalogs['en'].keys() == catalogs['fa'].keys(), 'Catalog key sets differ'
    print(f'PASS: {len(doc.ids)} DOM ids, 6 settings categories, 5 tools, 6 themes, 4 font sizes, {len(catalogs["en"])} locale keys; no radios, frames, or unsafe HTML sinks.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except AssertionError as error:
        print(f'FAIL: {error}', file=sys.stderr)
        sys.exit(1)
