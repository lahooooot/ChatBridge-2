# ChatBridge 2.60.0

ChatBridge is a Windows desktop workspace for browser-based AI chats. It combines a local chat surface, an internal WebView2 browser, project files and an editor, a live terminal, Git controls, editable agent rules, and an optional local OpenAI-compatible provider. The source uses Python and vanilla HTML/CSS/JavaScript; there is no frontend build step, extension, or iframe.

**This delivery contains source code, not a prebuilt Windows executable.** Automated tests run in Linux and use mock site DOMs in Chromium. Real signed-in ChatGPT, Claude, z.ai, DeepSeek and Gemini sessions, Windows native docking and installer execution still need Windows acceptance testing. See `docs/validation.md` for the actual evidence and outstanding checks. This is a new implementation from the supplied specification, not a recovered copy of a previously tested 2.48/2.49 application.

## Run on Windows

Install x64 Python 3.10 or newer and the Microsoft Evergreen WebView2 Runtime. Extract the ZIP into a normal writable directory, then double-click `ChatBridge.bat`. The launcher creates `.venv` and installs runtime dependencies on its first run. An Internet connection is needed for dependency installation and for web chat services.

Alternatively, run these commands in PowerShell from the extracted directory:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m desktop.app
```

Open **Internal Browser** from the always-visible globe button. Sign in to the selected site in that browser. Login cookies stay in `%LOCALAPPDATA%\ChatBridge\WebView2`; the app calls `webview.start(private_mode=False, storage_path=...)`. The companion is created hidden in a daemon worker and mounted as a Win32 child in the right dock. A floating window is used only if native mounting fails, and the recovery is reported honestly.

Attach a local project or create a chat folder before asking for local tool work. Send a message from the composer. The driver navigates to the owning web conversation, verifies composer insertion and sending, streams the assistant text, and forwards local tool results back to the same conversation. You can stop the current turn without queuing another automatic retry.

English is the default interface because the specification's opening section explicitly requires it. Persian RTL is available in Appearance/General settings. The later instruction asking for Persian by default conflicts with that opening instruction; this choice is recorded in `worklog.md`.

## Safety and local data

**Full Access is ON by default, as requested.** With it enabled, a model's write and command requests can run without an approval card. Turn it off before using an untrusted conversation. With Full Access off, write and command requests require approval; silence times out as denial.

Approval must come from the trusted desktop card. The page overlay can show the pending operation or deny it, but cannot grant execution: remote page JavaScript can synthesize clicks and replace its own DOM agent. This deliberately strengthens the original two-location approval proposal. Approving in the desktop closes both cards.

File tools resolve paths and symlinks and reject access outside the selected workspace. The editor rejects binary files and text files larger than 2 MB. A command runs with your OS account permissions: setting its working directory is not an operating-system sandbox, and a shell command can access resources elsewhere on the machine. Never grant Full Access to an untrusted site or prompt. Site automation may be restricted by that site's policies; use accounts and services you are authorized to access.

Configuration and history are stored in `~/.chatbridge/config.json` and `ui_state.json`. Operations are recorded in `audit.db`. Rotating logs are in `~/.chatbridge/logs/`; logs may include diagnostic URLs and operation details, so review them before sharing. The UI can export a log archive. Profile reset signs you out on the next restart instead of deleting files still locked by a running WebView2 instance.

Startup automatically migrates custom-model rows written by older preview builds: `url` is accepted as the old name for `home`, recognizable missing IDs are generated, and incomplete rows are removed. If an older build left a file that cannot be read at all, close ChatBridge and rename `%USERPROFILE%\.chatbridge\config.json` to `config.json.bak`; the next launch creates clean defaults. Do not delete `ui_state.json` unless you also want to reset conversations and layout.

If CMD repeatedly prints `AccessibilityObject.Bounds.Empty`, `HorizontalScroll.ParentControl.ModifierKeys`, or `maximum recursion depth exceeded`, rebuild the EXE from this source. Native objects must stay private on the pywebview API object: both the main `_window` and the internal `_browser` fields are private. Exposing either as public `window`/`browser` triggers a known WinForms accessibility recursion.

The packaged build is a single executable: `dist\ChatBridge-2.50.0.exe`. After `build_exe.bat` finishes, double-click that file or double-click `ChatBridge.bat`; Python and the source module are not needed at runtime. User data is isolated under `%USERPROFILE%\.chatbridge-2.60.0`, including `config.json`, `ui_state.json`, logs, and the WebView2 profile.

The build explicitly embeds every UI file and opens `desktop/ui/index.html` through an absolute `file://` URI. If an old EXE shows `127.0.0.1:42001/index.html` with `404 Not Found`, it was built from an earlier spec; delete `build` and `dist`, run the current `build_exe.bat`, and launch the newly generated `dist\ChatBridge-2.50.0.exe`.

The internal WebSocket binds only to `127.0.0.1:8787` by default and requires a per-process secret in its driver handshake. There is one authenticated driver slot. Changing the WS port requires a restart. File transfer is capped at 15 MB and upload success is reported only after a site attachment chip is detected. Page downloads are restricted to same-origin and blob resources; third-party image CDN URLs can be shown as links but cannot be fetched through this guarded path.

## Workspace contract (`agent.md`)

The first built-in rule instructs the model to look for an `agent.md` file at the workspace root as soon as a project is attached. If the file exists, its contents become part of the working contract for the session. If it does not exist, the model creates it and records the rules and conventions it settles on there, so future sessions inherit them. You can edit `agent.md` by hand at any time; it lives inside the workspace and is subject to the same path and approval rules as any other file.

## Local tools

The local tools fall into four groups. Workspace file tools: `read_file` (with `offset`/`limit`), `write_file` (full `content` or `search`/`replace`), `list_dir`, `search_files`, `stat_file`, `append_file`, `make_dir`, `delete_file`, `rename_file`/`move_file`, `copy_file`, `glob`, `grep`, `edit_file` (with `count` and `regex`), `diff_preview`, `read_multiple_files`, `tail_file`, `outline`, `find_symbol`, and `run_command`. Git tools: `git_status`, `git_diff`, `git_log`, `git_show`, `git_blame`, `git_stage`, `git_unstage`, `git_commit`, `git_branch`, `git_checkout`, `snapshot`, and `rollback`. Process and test tools: `process_control` and `run_tests`. Network tool: `http_fetch` (http/https only, loopback/private/link-local blocked, 2 MB cap). All paths stay inside the attached workspace. Requests use a standard code fence:

````text
```chatbridge-tool-call
{"tool":"read_file","args":{"path":"src/app.py","offset":0,"limit":120}}
```
````

`write_file` takes a path and full `content`, or a path with `search` and `replace` for an unambiguous patch. `edit_file` is the preferred way to patch existing files: it requires the search text to match exactly `count` times (default `1`, or `"all"`), supports `regex`, and returns a unified diff. `grep` adds a `glob` filter, `case_sensitive`, `fixed_strings`, `context_lines`, `max_matches` and `max_per_file`. `glob` walks `**` patterns and respects `.gitignore`. `read_file` accepts `offset` and `limit`, `tail_file` reads the end of large files, `read_multiple_files` batches several reads, and `outline`/`find_symbol` summarize or locate definitions. `stat_file`, `append_file`, `make_dir`, `delete_file`, `rename_file`/`move_file`, `copy_file` and `diff_preview` cover the rest of the file surface. `list_dir` takes `path` and optional `depth`; `search_files` takes `query` and optional `path`, `regex` and `max`; `run_command` takes `cmd` and optional `cwd` and `timeout` (default 300 seconds). Terminal output streams as it arrives, and cancellation terminates the process tree. Git tools wrap the same actions exposed in the panel (`git_status`, `git_diff`, `git_log`, `git_show`, `git_blame`, `git_stage`, `git_unstage`, `git_commit`, `git_branch`, `git_checkout`), plus `snapshot` and `rollback` which build on `git stash create`/`apply`. `run_tests` detects pytest, jest, go, or cargo and parses pass/fail/skip counts. `process_control` lists, inspects, or kills terminal jobs. `http_fetch` only fetches public http/https URLs and refuses loopback, private, and link-local hosts. Writes, deletes, moves, Git mutations, `snapshot`/`rollback`, `run_tests`, `process_control`, and `http_fetch` require approval unless Full Access is enabled.

The canonical Python parser handles fenced JSON, raw string control-character repair, trailing commas, permitted Persian ZWNJ paths, broken blocks and DeepSeek DSML variants. Malformed contract output produces a steering error instead of silently ending the conversation. The desktop renders tool activity as operation rows rather than exposing the raw contract fences. Each request has a 16-round tool budget, and queued results are still delivered in the final grace capture. Large results are stored under the workspace's `.chatbridge/results/`, with a short preview and a real attachment when it fits the transfer cap.

## Provider server

Enable the provider in Settings. It binds to `127.0.0.1:8788`, exposes `GET /v1/models` and `POST /v1/chat/completions`, and uses the generated key shown in the UI. The internal browser must be open and signed in. Available models are `web-chatgpt`, `web-claude`, `web-deepseek`, `web-zai` and `web-gemini`.

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8788/v1", api_key="KEY_FROM_SETTINGS")
response = client.chat.completions.create(
    model="web-chatgpt", messages=[{"role":"user","content":"Hello"}]
)
print(response.choices[0].message.content)
```

Streaming uses SSE. Tool fences are converted to native `tool_calls` for the external client; requests prefixed `prov-` never execute local desktop tools. Token usage is unavailable from web pages, so the response includes `chatbridge.usage_is_unavailable: true` and zero-valued usage counters rather than invented estimates. This is a practical chat-completions facade, not the full OpenAI API: audio, vision content blocks, embeddings, Responses API, logprobs and arbitrary generation parameters are not implemented. One browser serializes turns; parallel API calls queue and are not independent parallel web sessions.

Each HTTP completion starts a fresh web conversation and sends the full client-supplied transcript. It must not inherit a previously open desktop conversation. Multi-turn API clients should send their accumulated messages on each request; the provider does not reuse hidden browser context.

## Build Windows executable and installer

Run `build_exe.bat` on Windows x64 with x64 Python. PyInstaller creates `dist\ChatBridge\ChatBridge.exe` in onedir format. Run `build_installer.bat` after installing Inno Setup 6 to create `installer-output\ChatBridge-Setup-2.50.0.exe`. The installer keeps user config/profile data when the app is uninstalled and warns when WebView2 Runtime is not detected. Build artifacts are not signed.

The supplied `.spec`, `.iss` and batch files are source build recipes. Their native build and installed-app execution were **not** run in this Linux environment. Do not treat their presence as proof that a Windows installer was produced.

## Tests

For platform-neutral source checks you only need pytest, pytest-asyncio, websockets, Playwright and BeautifulSoup. For a full Windows development environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe scripts\run_checks.py
```

The checks compile every Python module, run `node --check` on JavaScript (Node.js must be installed), verify version markers and DOM pins, execute pytest, and run the UI and page-agent mock tests in Playwright. Windows native acceptance is separate from mock DOM tests. Selectors are centralized at the top of `desktop/agent_cb.js`; use the page agent's `probe()` and Browser log to diagnose site changes. A site layout, anti-bot gate or CSP change can require an adapter update and cannot be guaranteed by offline mocks.

## Source layout

`desktop/app.py` exposes the desktop API. `bridge.py` owns the single-client WS transport; `internal_browser.py` owns native docking and capture; `agent_cb.js` owns DOM discovery, markdown, sending and file transfer. `toolparse.py` is the canonical parser used by both driver and provider. Security, file tree, projects, terminal, Git, config and audit modules are separate. `desktop/ui/` contains the no-build interface. `shared/protocol.json` is the versioned wire contract, and `tests/` and `scripts/` hold automated checks. The original requested specification is preserved in `docs/original-spec.md`.

Technical references used to check desktop calls: [pywebview API](https://pywebview.flowrl.com/api/) and [multiple-window example](https://pywebview.flowrl.com/examples/multiple_windows).
