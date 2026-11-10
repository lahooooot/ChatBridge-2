# ChatBridge 2.50.0 validation

## What was built and checked

This source was implemented in a Linux ARM64 sandbox with Python 3.12 and Node.js 22. Native Windows APIs are guarded by platform checks. The desktop API can be instantiated for unit testing without loading pywebview; a non-Windows launch exits with an explanatory message instead of crashing.

The Python test suite covers the canonical parser, one authenticated WS slot and reclaim, UI event queue, editable rule migrations, confined file access/tree/editor, terminal streaming and cancellation, actual Git repositories and local bare remotes, Provider auth/completion/SSE/native tool calls, desktop API integration, owner workspace switching, request-scoped stop, stale capture and optimistic text movement. Final run evidence is saved in `pytest-output.txt` and `checks-output.txt`.

The Playwright scripts exercise synthetic DOM fixtures, not logged-in production sites. UI mocks exercise the native API boundary without exposing actual files or running real model commands. Page mocks test the five built-in site adapters and the generic adapter, including composer injection, DeepSeek PoW verdicts, markdown conversion, shadow roots, multi-unit responses, scoped limits, upload verification, downloads, transcript loading, approvals and navigation. Final counts are recorded after the integrated run below.

## Native Windows acceptance still required

The source build recipes are present, but **no `ChatBridge-Setup-2.50.0.exe` or installed Windows application was produced or executed in this environment**. PyInstaller and Inno Setup must run on Windows x64. The acceptance item requiring a built and launched installer is therefore not satisfied by this source-only delivery.

The WinForms accessibility recursion reported by a Windows user was traced to a public `js_api.window` native Window field. It was changed to private `_window`, matching the workaround documented in [pywebview issue 1815](https://github.com/r0x0r/pywebview/issues/1815). An existing frozen EXE cannot receive this fix; it must be rebuilt.

The WebView2 child must be checked inside the actual right dock with no separate taskbar entry, at 100%, 125%, 150% and mixed-monitor DPI scaling. Move and resize the main window, drag both separators, open/close Settings, hide/reveal the dock, and restart with persistent cookies. The ctypes Win32 code is source-checked here, not exercised against real HWNDs.

Sign in to ChatGPT, Claude, z.ai, DeepSeek and Gemini in the internal browser and run one message, one streamed response, one stop, one five-tool roundtrip, one upload and one returned file on each. Also test a custom chat site. Synthetic fixtures prove adapter mechanics only; they do not prove current production selector accuracy, trusted event acceptance, anti-bot/PoW behavior under real network conditions, CSP compatibility, or account/session policy compliance.

Check the approval card in both windows with Full Access disabled, approve in the trusted desktop UI and verify that both cards disappear, let an unanswered request expire, and stop while a command is running. The web-page overlay deliberately cannot authorize operations because its JavaScript is untrusted; it may deny or display status. Verify real Windows `taskkill /T /F` cancellation including descendants. With Full Access enabled, commands run with the current account's full permissions; they are not OS-sandboxed.

## Acceptance coverage

The always-visible browser control, operation rows without raw fences, file tree/editor, two direction-correct draggable boundaries, collapsible sidebar, six settings categories, zero-radio browser settings, editable/master-toggle rules and local persistence have source and automated coverage. Live Windows docking/login, continuous responsiveness of native WebView2, real-site send/capture/file transfer and installed-application execution remain manual checks rather than claimed passes.

The 16-round budget and grace capture are implemented in the driver. Single retries are forbidden after request-scoped stop. Owner workspace snapshots and request IDs prevent a UI project change from redirecting an already-dispatched local tool. Recent conversation text is transferred when a chat changes service; saved web URLs are validated against the selected service origin before reuse.

## Deliberate constraints

The interface defaults to English despite the conflicting later Persian-default sentence in the supplied specification. The provider implements local chat completions and models, not every OpenAI endpoint or option. Token usage is not available from web pages. File downloads deliberately reject cross-origin resources. Text tools/editor are limited to UTF-8 text up to 2 MB. Transfers are limited to 15 MB. Huge directories, retained terminal output, terminal histories, WS/UI queues and request routing state are bounded.

The companion browser is a single resource, so queued requests are serialized. It is not a multi-account parallel browser farm. A dock failure produces a visible floating recovery and diagnostic instead of a dead black panel. Profile deletion is deferred to restart to avoid deleting locked WebView2 files.

## Final automated run

The final pytest run passed **365 tests in 12.03 seconds**, with no failures or warnings. The consolidated check passed Python compilation, all JavaScript `node --check` commands, synchronized 2.50.0 version markers, 143 DOM ID pins, six settings categories, five tool names, six themes, four font sizes, and 207 keys in each locale. The DOM check found no radio inputs, frames, or unsafe HTML sinks.

Playwright passed **47/47 page-agent cases** and **15 UI acceptance groups** after the security/lifecycle changes. The consolidated run took the Python suite before one final queued-cancellation regression was added; `pytest-output.txt` records the subsequent 365-test run against the final source. `checks-output.txt` records the complete compiler/DOM/version/Playwright run. The final added native-stop/queued-owner paths also passed their targeted regression run. No Windows installation or signed-in live-site execution is implied by these results.
