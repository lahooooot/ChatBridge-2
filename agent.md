# ChatBridge working contract

This file is the persistent contract between the ChatBridge desktop app and the
web model attached to this workspace. Any agent that opens this workspace must
read it first, follow it for the session, and extend it with new rules as they
are settled.

## Project overview

ChatBridge is a Windows desktop app (Python + pywebview + native WebView2) that
bridges browser-based AI chats to local tooling. Current version: 2.60.0.

Key locations:

- `desktop/` — Python backend (API, bridge, terminal, Git, tool parser, safety)
- `desktop/tools/` — local tool implementations
- `desktop/ui/` — no-build HTML/CSS/JS interface
- `shared/protocol.json` — versioned WebSocket wire contract
- `tests/` — pytest suite (`pytest -q`)
- `scripts/` — build, version, packaging and validation helpers

## Rules settled so far

1. **Version markers** — one source of truth in `desktop/app.py` (`APP_VERSION`).
   Bumping requires `python scripts/bump_version.py X.Y.Z` then
   `python scripts/sync_installer_version.py` then
   `python scripts/ver_check.py`. `scripts/package_source.py` regenerates
   `source-manifest.json`.
2. **Tool surface** — the five original tools are `read_file`, `write_file`,
   `list_dir`, `search_files`, `run_command`. Extended tools must be registered
   in `desktop/tools/__init__.py` and dispatched from `desktop/app.py`; anything
   that mutates state, writes files, runs tests, controls processes or fetches
   URLs belongs in `APPROVAL_TOOLS`.
3. **Editing** — prefer `edit_file` for local edits; it must match exactly
   `count` times (default 1) and returns a unified diff. Use `write_file` only
   to create or replace a whole file.
3b. **Tool-result ordering (nonce protocol)** — the bridge can deliver results
   out of order, so never trust a result that doesn't carry the expected token.
   Give every operation a unique nonce (e.g. `FINISH7Q2`); `run_command` prints
   it as its first stdout line and report files start with `REPORT-NONCE <nonce>`.
   Only treat a result as current when the nonce matches; otherwise it is stale.
   Also: dependent `write_file` -> `run_command` calls must be sent in separate
   messages (same-message calls run concurrently and can race).
4. **Reads** — `read_file` accepts `offset`/`limit`; use `tail_file` for logs,
   `outline` for a symbol summary and `find_symbol` before editing.
5. **Workspace confinement** — all file paths are resolved inside the workspace
   root; symlinks are not followed; `delete_file` refuses to delete the root.
6. **Tests** — run `python -m pytest -q` (via `.venv\Scripts\python.exe` on
   Windows) before claiming success. Pre-existing tests must stay green.
7. **Build** — `build_exe.bat` produces `dist\ChatBridge-2.60.0.exe`;
   `build_installer.bat` produces `installer-output\ChatBridge-Setup-2.60.0.exe`.
   `scripts/ver_check.py` gates the build.
8. **Documentation** — user-facing changes update `README.md`; the HTML guide
   is regenerated with `python scripts/render_readme.py`; user-visible changes
   get a `CHANGELOG.md` entry under the current version.
9. **Data directory is stable** — user data lives in `%USERPROFILE%\.chatbridge`
   (not version-suffixed). `RULES_VERSION` in `desktop/config.py` still versions
   the built-in agent rules only. On first launch, `default_data_dir()` and
   `profile_path()` copy the newest legacy `.chatbridge-X.Y.Z` folder (app data
   and WebView2 profile) into the stable folder. Copy, never move; the legacy
   folder is kept as a backup. Do not reintroduce version-suffixed data dirs.

10. **Coverage gate for working-tree changes** — a change may stay in the working tree only if the pytest suite exercises it. This repo has no `pytest-cov`/`coverage` in `.venv`, so measure coverage with a stdlib probe (`sys.settrace`, see `.chatbridge/cov_probe.py`) or write a targeted assertion in `tests/`. A change counts as covered only when a test asserts the new behaviour: JS/HTML edits (`desktop/agent_cb.js`, `desktop/ui/index.html`) need an explicit test, and a new Python parameter needs a test that actually passes it. Never leave a half-finished parameter in the tree — a dead parameter such as `attachments` silently drops user input. Cancel uncovered changes with `git checkout -- <file>` after saving a backup patch (`.chatbridge\uncovered_backup.patch`).

11. **Provider model registry** — the exposed model list comes from
    `desktop/provider_models.py` (built-in platforms plus the user's custom
    models). Never hardcode model ids and never slice a platform id out of a
    model id; every model carries an explicit `platform`. Agent setup
    snippets live in `desktop/provider_presets.py` as a data-driven registry,
    so any OpenAI-compatible desktop agent is one entry away and the UI is
    never limited to a fixed list of products.
12. **Provider settings surface** — Settings > Provider Server shows the
    live server state, the base URL, the access key (show plus copy), a test
    button and the exposed models. The key may only be rotated behind an
    explicit user confirmation, and ChatBridge must never write into an
    agent's own configuration file or `.env`; it produces a snippet and the
    user merges it.
13. **The DOM gate stays green** — `scripts/ui_dom_check.py` is the
    acceptance gate for every UI edit: its pins must match the elements that
    actually exist (no stale pins, no removed elements), it must read files
    as UTF-8 so it also runs on Windows, and `desktop/ui/app.js` must not
    build HTML strings for injection (`innerHTML` and friends stay banned).
    **Native-layer rule:** the internal browser is a real WebView2 window that
    floats above the DOM, so a `<dialog>` does *not* cover it. Every modal that
    can open while the browser is docked must (a) be in the `visible` guard in
    `window.__cbIbDockRect` (`!$('...Modal').open`) and (b) call `sendIbFit()`
    on open and on `close`. The paste dialog missed both and fell behind the
    browser; `tests/test_ui_paste_modal.py` pins the fix. Follow the
    `hintModal`/`confirmModal` pattern for any new dialog.

14. **Conversation handoff and the offline translation bundle** — the web
    chat never exposes real token counts, so the budget is estimated
    (`TOKEN_PER_WORD = 1.3` on the transcript). The limit is **not** a
    constant anymore: `config.token_limit` (default 4000, 500..50000) is the
    global budget and `config.token_limits` maps a platform id to a per-model
    override; `Api._token_limits(platform)` resolves both and returns
    `(warn, limit)` with `warn = round(limit * 0.88)`. Never hardcode 3400/3900
    in new code — read the config. The automatic path asks the web
    model for a summary delimited by `CB-SUMMARY-START`/`CB-SUMMARY-END`, then
    hands it to a fresh chat with `send_message(..., include_rules=True,
    fresh=True)`; `token_limit_stop` cancels the automatic path only. The
    offline snapshot `window.__CB_BUNDLED_TRANSLATIONS` in `desktop/ui/i18n.js`
    must mirror `desktop/translations/en.json` and `fa.json` exactly
    (`tests/test_provider_settings.py::test_offline_bundle_mirrors_the_json_catalogs`
    is the gate) — regenerate it after every catalog edit, never splice the
    JSON line with a regex on `};` (it also appears inside string values).

## Session log

- 2026-11-14 — created. Recorded the initial rules above after upgrading to
  2.60.0 and validating the extended tool suite.
- 2026-11-14 — fixed `run_tests` in `desktop/tools/_extended.py`: dropped the
  broken `\.venv/...` candidate in `_python_for` and made the pytest command
  use the resolved `python` (venv-aware) instead of a hardcoded `"python"`.
  Full suite green (375 passed, 5 skipped); handler verified end-to-end in a
  fresh subprocess. Note: the live Desktop API caches modules at startup, so
  restart the app before live `run_tests` calls reflect source edits.
- 2026-11-14 — fixed `git_status` in `desktop/tools/_extended.py`: it called
  `_git(..., "status")`, but `GitTools.action()` has no `status` case (that is a
  separate method), so every `git_status` call returned `Unknown Git action:
  status`. It now calls `GitTools(root).status()` directly.
- 2026-11-14 — made the data directory stable across upgrades. `DATA_DIR_NAME`
  is now `.chatbridge` (was `.chatbridge-2.60.0`); `default_data_dir()` and
  `profile_path()` copy the newest legacy versioned folder once on first launch
  so settings, history and model logins survive. Added a migration test; full
  suite green (376 passed, 5 skipped).
- 2026-11-14 — fixed the opaque `'cmd'` error from `run_command`: the
  `run_command` branch in `desktop/app.py` read `args['cmd']` directly (a bare
  `KeyError: 'cmd'` surfaced before the tool's own validation). It now accepts
  `command` as an alias for `cmd`, rejects unknown keys, and raises a clear
  `ValueError` for a missing/empty command. `desktop/tools/run_command.py` is
  unchanged, so `tests/test_safety.py`'s `command`-rejection contract still
  holds (that test calls `execute` directly, not the app branch). Full suite
  green (375 passed, 5 skipped).

- 2026-11-14 — fixed the recurring `no-tab` / `WebView script timed out`
  failure on Gemini and ChatGPT in `desktop/internal_browser.py`. Root cause
  was a race: `_late_ready` and the `_inject` retry timer could start several
  concurrent `_inject` calls, each grabbing `_eval_lock` and force-releasing
  it on timeout, so one successful injection was immediately invalidated by
  the next timeout. `_ensure` also waited only 25 s, shorter than the worst
  case of two 12 s injections. Changes: added `_inject_lock` (non-blocking
  acquire; duplicate attempts return immediately), moved the `reinject`
  `Timer(4.0, ...)` back into the `except` branch (it had drifted into
  `finally` and fired on success too), and raised the three `_ensure` waits
  from 25 s to 45 s. `py_compile` green; `run_tests` green (376 passed,
  5 skipped). One separate run under concurrent pytest load showed a
  flaky `tests/test_fstree.py::test_concurrent_writes_are_complete_and_preserve_mode`
  (`WinError 5` on `os.replace` in `desktop/safety.py`); this is unrelated to
  the browser change and must be re-checked in isolation.
- 2026-11-14 — tool-result ordering is visibly unreliable on this bridge:
  several `run_command`, `list_dir`, `read_file` and `stat_file` replies
  arrived out of order or replaced by an earlier request's output. The nonce
  protocol in rule 3b is not optional here; until `run_command` accepts a
  `nonce` argument (it currently rejects it with `Unknown tool arguments`),
  prefer one tool request per message and write long command output to a file
  that `read_file` can fetch later.
- 2026-11-14 — fixed Gemini/ChatGPT messages not being sent (text never reached the web composer, so the Send button never appeared). Two root causes:
  (1) `inject()` in `desktop/agent_cb.js` gated every injection strategy on `focus(el) === true`; Gemini keeps `<rich-textarea>` as `document.activeElement` while the real editable is the inner `div.ql-editor`, so `focused()` returned false and all strategies were skipped (`inject-verify`). Fixed by widening `focused()` to walk the activeElement's ancestors (so an ancestor host counts as focused) and by making `inject()` call `focus(el)` best-effort and rely on `carries(el, text)` as the real verification gate.
  (2) A stale user file `%USERPROFILE%\.chatbridge\platform_hints.json` had a manual `gemini.google.com` entry whose `editor` selector targeted `div:nth-of-type(2)` = Quill's hidden `.ql-clipboard`, not the real `.ql-editor`; `agent_cb.js` prepends custom hints, so `findEditor()` returned the clipboard and injection went nowhere. Also its `send`/`body` selectors were wrong (`button ... > span` and the zero-state container). Deleted the file (user approved, no backup) so both Gemini and ChatGPT fall back to the built-in defaults (`div.ql-editor[contenteditable="true"]`, `button.send-button` / `button[data-testid="send-button"]`, `message-content` / `.model-response-text`).
  Verified: `node --check desktop/agent_cb.js` → NODE_OK; full suite green twice (376 passed, 5 skipped); snapshot `before-inject-focus-fix` (stash `0adca9be`). User confirmed sending works on both sites.
  Lesson: when a site fails to receive injected text, check `%USERPROFILE%\.chatbridge\platform_hints.json` first — a stale hand-edited hint silently overrides the built-in selectors and is not covered by any test.

- 2026-11-14 — selector picker became test-driven. `pickerStart` in `desktop/agent_cb.js` now calls `pickerConfirm(mode, cands, info)`: it builds candidates from the clicked element plus its ancestors (up to 5 levels, stopping at MAIN/FORM/BODY), shows a `data-cb-ui` bar at the bottom of the page, and lets the user test each candidate with real injection (`inject` + `carries`) before confirming. For `mode==='send'` a «تست ارسال» button injects TEST_TEXT ('این یک پیام برای تست ارتباط بین من و تو است'), clicks the chosen candidate, waits 1500ms, and accepts only if `reading().count` grew or `findStop()` appeared. The confirmed candidate(s) are emitted as `picker_pick` with `candidates`/`chosen`; `desktop/ui/app.js` stores the chosen path in `hintState`. Ordering gate: `startPick('send')` refuses until `hintState.editors` is non-empty. Reset: `hintResetBtn` (in `desktop/ui/index.html`) calls `hints_set(host, {})` after a confirm dialog, clearing saved selectors for that host and falling back to built-in defaults; `hintState` is cleared and re-rendered.
- 2026-11-14 — `edit_file` lesson confirmed in practice: search text with multiple lines fails to match on CRLF files (`internal_browser.py`, `agent_cb.js`, `app.js`, `index.html`) because `read_file` returns `\r\n` while the file's stored bytes interleave differently; single-line searches match reliably. Rule: keep `edit_file` `search` single-line unless the multi-line text was just read verbatim and `count` is verified. When a multi-line search is unavoidable, split into several single-line edits.
- 2026-11-14 — diagnostic logging added (to be removed or demoted to DEBUG after the send bug is fixed): `evaluate()` logs worker start and timeout with `worker.alive` and `_eval_lock.locked()`; `_inject` logs `active_turn` and probe+snap duration; `_turn` logs `turn-send start/done` with elapsed ms; `agent_cb.js` logs `send-busy-enter/exit`, `send-busy-wait`, `send-diag` (per send selector: n/visible/enabled/disabled/aria-disabled), `waitready-poll`, and `probe-no-send`. These must not be left at INFO in a release build.
- 2026-11-14 — full test suite green after the picker and logging changes (376 passed, 5 skipped). `node --check desktop/agent_cb.js` and `node --check desktop/ui/app.js` passed before the suite.

- 2026-11-16 — removed dead browser chrome per user request (both did nothing).
  `desktop/ui/index.html`: dropped the submit `<button title="Navigate">↗</button>`
  from `#urlForm` (Enter still submits via the existing `urlForm` submit
  handler) and removed the whole `div.browser-foot` (connection dot,
  `#browserState`, `#reinjectBtn`, `#browserLogBtn`) plus `pre#bbLog`.
  `desktop/ui/app.js`: made `updateStatus` null-safe for `#browserState`,
  made `logBrowser` bail out when `#bbLog` is absent, and dropped the now-dead
  `reinjectBtn`/`browserLogBtn` bindings. `bind()` already uses `?.`, so
  remaining optional elements are safe. Verified: `node --check
  desktop/ui/app.js` → NODE_OK; full suite green (376 passed, 5 skipped).
  Rule for future UI removals: any element referenced by `$('id')` in app.js
  must be guarded (null check) before deleting its HTML, or the UI throws on
  load; `bind()` is already guarded but direct `.textContent`/`.classList`
  access is not.
- 2026-11-16 — released 2.70.0. Ran `python scripts/bump_version.py 2.70.0 --old 2.60.0`, `sync_installer_version.py`, `ver_check.py` ("Version markers are synchronized: 2.70.0"), `package_source.py`; full suite green (376 passed, 5 skipped). Bump script's default `--old` is 2.50.0, so always pass the real current version explicitly or it reports `changed: 0 file(s)`. Tagged `v2.70.0`.
- 2026-11-16 — added in-app self-update (GitHub releases). New `desktop/updater.py`: `check_for_update()` hits the GitHub `/releases/latest` API with `urllib`, compares `tag_name` to `APP_VERSION`, and picks a portable `ChatBridge-*.exe` asset; `apply_update()` downloads it, stages a `cmd` batch in `%TEMP%\chatbridge-update` that waits for the PID, replaces the running EXE and relaunches. `Api.update_check`/`update_apply` wire it to the UI; on success the app calls `webview.stop()` then `os._exit(0)` so the batch can swap the locked file. Config gains `auto_update` (default True). UI: an `#updateBanner` under the header (Update now / Later) plus General-settings rows (`autoUpdateSwitch`, `checkUpdatesBtn`, `updateStatusText`); `checkUpdates()` runs automatically 1.2 s after bootstrap when `auto_update` is on. i18n keys added to en/fa. Rule: self-update only works in the frozen portable EXE (source checkout returns `not-frozen`); releases must attach the portable `ChatBridge-X.Y.Z.exe` asset for updates to work. Verified `py_compile` + `node --check` + full suite green (376 passed, 5 skipped).
- 2026-11-16 — cancelled the untested working-tree changes after a coverage review: (a) the multi-attachment `send_message` in `desktop/app.py` (`attachments` was dead code — the UI only ever sends one attachment and the body still used `file = attachment`, so a multi-file message would have gone out with no file at all), (b) `multiple` on the composer file input in `desktop/ui/index.html` (no test references that file, and on its own it lets the UI collect several files while only the first is sent), (c) the extra Claude `send` selectors in `desktop/agent_cb.js` (the only test touching that file asserts three generic strings, never the selectors). Backup patch: `.chatbridge\uncovered_backup.patch`. New rule 10 below.
- 2026-11-17 — completed the provider settings and agent onboarding. New
  `desktop/provider_models.py` is the single source of truth for the exposed
  models (built-in platforms plus user custom models, explicit platform
  mapping, no string-slice mapping); new `desktop/provider_presets.py` holds
  the data-driven registry of ready-to-paste snippets (opencode JSON,
  Hermes YAML plus the `.env` line, generic JSON/YAML/env, curl) so any
  OpenAI-compatible desktop agent can be added with one entry.
  `desktop/provider_server.py` now serves the configured model list, answers
  `GET /v1/models/<id>` and maps every model id to its browser platform.
  `desktop/app.py` gained `provider_models()`, `provider_test()` and
  `provider_key_rotate()`; Settings > Provider Server now shows live state,
  copy buttons for base URL and key, a manual key rotation behind a
  confirmation, the exposed model list and the agent snippet panel.
  ChatBridge never writes into an agent config or `.env`; the user copies the
  snippet. Verified: `pytest -q` green (394 passed, 5 skipped; +11 new tests
  in `tests/test_provider_settings.py`), `node --check` green,
  `scripts/ui_dom_check.py` green (186 ids, 246 locale keys).
- 2026-11-17 — repaired the pre-existing red DOM gate. `scripts/ui_dom_check.py`
  read files with the locale codec (UnicodeDecodeError on Windows), pinned
  elements deleted on 2026-11-16 (`browserSplitter`, `bbLog`) and a `browser`
  tab that no longer exists; all three are fixed. The last red assert was a
  pre-existing `innerHTML` sink in the code highlighter, so `highlightCode()`
  now returns DOM nodes (same spans and classes) and `updateLines()` uses
  `replaceChildren()`; no HTML string is injected anymore.

- 2026-11-21 — added three user features. (1) The composer is right-to-left:
  `dir="rtl"` on `#composerInput` plus `.composer textarea[dir="rtl"]{text-align:right}`.
  (2) Paste a tool request: `Api.paste_execute(payload)` in `desktop/app.py`
  parses a JSON tool call or treats the text as a `run_command`, executes it
  through `_execute_tool` so the result travels the normal `tool_result`
  bridge path, and the UI dialog `#pasteModal` (opened by `#pasteBtn`) calls
  it. (3) Automatic conversation handoff (rule 14): token estimate + banner +
  `token_limit_stop` + `summarize_now` + `summary_accept`, with the
  `token_warning`/`summary_migrate`/`summary_failed` UI cases. `send_message()`
  gained `fresh=False` for the new-chat hop. Locale keys and the offline
  `i18n.js` snapshot were regenerated; six DOM pins were added. Verified:
  `py_compile` green, `node --check` green (app.js, i18n.js), DOM gate green
  (202 ids, 273 keys), `pytest -q` green (420 passed, 5 skipped). The
  recurring `test_cross_instance_concurrent_atomic_updates_and_state`
  `PermissionError` flake fired once under load and passed in isolation — it
  is unrelated to these changes. Lesson: do not rebuild `i18n.js` line 49 with
  a `rsplit('};', 1)` — `};` also occurs inside string values (the first
  attempt corrupted the file); rebuild from `git show HEAD:desktop/ui/i18n.js`
  and replace only the full `window.__CB_BUNDLED_TRANSLATIONS = ...;` statement.

- 2026-11-21 — made the token budget configurable. `desktop/config.py` gains
  `token_limit` (default 4000, validated 500..50000) and `token_limits`
  (platform id → int); `Api._token_limits(platform)` resolves the override and
  returns `(warn, limit)` with `warn = round(limit * 0.88)`. `_event`,
  `token_status` and the auto-summary path read it instead of the old
  `TOKEN_WARN`/`TOKEN_LIMIT` constants (the constants remain only as fallbacks
  for a missing config). Settings > General gets `#tokenLimitInput`;
  `renderModels()` puts a small `token-limit-input` next to every model that
  writes `config.token_limits`. Locale keys `token_limit` /
  `token_limit_description`, offline `i18n.js` snapshot, `ui_dom_check.py` pin
  and two `test_agent_rules.py` cases were added. Note: the offline i18n line
  must be rebuilt from the full prefix (`window.__CB_BUNDLED_TRANSLATIONS = `)
  and the catalogs, not by regex-splitting on `};` — see the 2026-11-21 lesson
  above. Verified: `py_compile` green, `node --check` green, DOM gate green
  (203 ids, 275 keys), `pytest -q` green (422 passed, 5 skipped).
