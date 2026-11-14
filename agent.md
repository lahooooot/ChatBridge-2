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
- 2026-11-14 — fixed the opaque `'cmd'` error from `run_command`: the
  `run_command` branch in `desktop/app.py` read `args['cmd']` directly (a bare
  `KeyError: 'cmd'` surfaced before the tool's own validation). It now accepts
  `command` as an alias for `cmd`, rejects unknown keys, and raises a clear
  `ValueError` for a missing/empty command. `desktop/tools/run_command.py` is
  unchanged, so `tests/test_safety.py`'s `command`-rejection contract still
  holds (that test calls `execute` directly, not the app branch). Full suite
  green (375 passed, 5 skipped).
