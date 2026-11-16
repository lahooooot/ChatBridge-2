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
