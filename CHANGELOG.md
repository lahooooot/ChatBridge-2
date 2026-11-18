# Changelog

All notable changes to ChatBridge are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- Provider requests no longer fail silently when the internal browser was never
  opened. `POST /v1/chat/completions` now opens the browser itself, waits for
  the driver to connect, and only returns `503 browser_unavailable` when it
  really cannot connect, with a message that says what to do.
- The provider accepts the model name a client actually sends: `web-chatgpt`,
  the provider-qualified `chatbridge/web-chatgpt`, and any letter case all
  resolve to the same exposed model instead of `400 Unknown web model`.

### Added
- `GET /health` reports the server and browser state plus the exposed models.
- `provider_probe()` sends one real completion through the whole chain
  (HTTP → bridge → internal browser → web chat) and reports the reply, so the
  settings panel can show where a client request stops.
- A live status card at the top of Settings > Provider Server: server, internal
  browser and exposed-model checks, a **Send test message** button and the web
  reply. The section is now grouped as General, Connection, Security, Server
  status and Connect an agent.
- The provider section is fully translated to Persian, including the group
  headings and the security note.

## [2.71.0] - 2026-11-11

### Added
- The provider server now follows the models you configured. Every built-in
  web chat and every custom model is exposed as `web-<platform id>` with an
  explicit platform mapping, `GET /v1/models` lists them and
  `GET /v1/models/<id>` returns a single model.
- Settings > Provider Server is now a complete setup surface: live server
  state, a **Test connection** button, copy buttons for the base URL and the
  access key, a manual key rotation behind a confirmation, the list of
  exposed models, and a **Connect an agent** panel that produces a
  ready-to-paste provider block for opencode, Hermes or any other
  OpenAI-compatible client (JSON, YAML, environment variables or curl).
  ChatBridge never edits an agent configuration file; the user merges the
  snippet.
- New desktop API methods: `provider_models()`, `provider_test()` and
  `provider_key_rotate()`.
- Thirty new local tools across four groups. Workspace file tools:
  `edit_file`, `stat_file`, `append_file`, `make_dir`, `delete_file`,
  `rename_file`/`move_file`, `copy_file`, `glob`, `grep`, `diff_preview`,
  `read_multiple_files`, `tail_file`, `outline`, `find_symbol`, with
  `read_file` gaining `offset`/`limit` coverage. Git tools:
  `git_status`, `git_diff`, `git_log`, `git_show`, `git_blame`,
  `git_stage`, `git_unstage`, `git_commit`, `git_branch`, `git_checkout`,
  `snapshot`, `rollback`. Process and test tools: `process_control`,
  `run_tests`. Network tool: `http_fetch` (http/https only, loopback/
  private/link-local blocked, 2 MB cap).
- `agent.md` workspace contract: the first built-in rule makes the model
  look for `agent.md` at the workspace root when a project is attached,
  follow its contents as part of the session contract, and create or
  extend it with rules settled on during the session.
- Approval is now driven by `APPROVAL_TOOLS` in `desktop/app.py`, so
  every mutating tool (writes, deletes, moves, Git mutations, snapshots,
  test runs, process control, and `http_fetch`) asks for approval unless
  Full Access is enabled. The read-only tools remain approval-free.
- Right-side chat navigation rail with one marker per user message.
  Hovering the chat panel reveals it; clicking a marker smoothly scrolls
  to that message and the marker for the message in view stays highlighted.
- Visible "No project" row at the top of the workspace list while a chat
  has a project attached. Clicking it detaches the project from the chat
  without deleting it, so it can be re-attached in one click.
- GitHub Actions CI (version synchronization + full test suite on two
  Python versions) and a tag-driven release workflow that builds the
  Windows executable and Inno Setup installer and publishes them with
  SHA-256 checksums.

### Changed
- User messages now render in a distinct bubble so they stand out from
  assistant messages at a glance.
- A single tool operation is shown directly instead of being wrapped in
  a collapsed history group; two or more are still grouped.
- Versioning is centralized: the git tag (`vX.Y.Z`) must match
  `APP_VERSION` and `scripts/ver_check.py` enforces the rest.

### Fixed
- Upgrades no longer wipe settings, chat history and saved model logins.
  User data now lives in a stable `%USERPROFILE%\.chatbridge` folder
  instead of a version-suffixed `.chatbridge-X.Y.Z` one. On first launch
  after upgrading, the newest versioned folder is copied into the stable
  folder (the old folder is kept as a backup), for both app data and the
  WebView2 login profile.
- Explanatory prose was deleted whenever a tool-call fence was followed
  by text on the same line as the closing fence. Fixed in both the
  Python parser (`desktop/toolparse.py`) and the UI stripper
  (`desktop/ui/app.js`); the closing fence is now consumed without
  swallowing the sentence that follows it.
- Prose was dropped during page capture when a message container mixed a
  code block with nested explanatory text (`desktop/agent_cb.js`).
- `run_command` on Windows returned the wrong exit code and empty output
  because the command line was passed to `cmd.exe` as a list and got
  re-quoted. It is now built as a single command line.
- Command timeouts were reported as `timed_out: false` even when the
  command never finished.
- Terminal output kept Windows `CRLF` line endings; it is normalized to
  `\n` so comparisons and copies behave consistently.
- A stale WebView evaluation lock could wedge the browser forever after
  a hung native call; the lock is now cleared before the closed-browser
  error is raised.

### Security
- Release assets are published with a `SHA256SUMS.txt` file generated by
  the release workflow.

## [2.71.0] — initial public baseline

First tagged source baseline for the GitHub repository
[lahooooot/ChatBridge-2](https://github.com/lahooooot/ChatBridge-2).
