# ChatBridge 2.50.0 worklog

## 2.50.0 — source implementation

This is a new implementation from the supplied specification, not a modification of a pre-existing release. The architecture uses a single internal WebView2 browser driver, a loopback authenticated WebSocket bridge, a vanilla desktop UI, and Python tools. There is no extension and no browser-mode selection.

The implementation is developed and tested in Linux. Native Windows docking, persistence of real-site login, Windows installer execution, and signed-in live-site behavior must be validated on Windows; no Windows binary is claimed from this environment.

## Decisions

- English is the default interface because section 0 explicitly requests English; Persian RTL is selectable (section 13 conflicts on the default).
- Loopback services use a random token, including the internal driver, to prevent arbitrary local clients from gaining tool access.
- Full Access follows the requested default ON, but all file operations remain confined to the selected workspace and symlinks are resolved before access. The UI warns that commands run with the user's permissions.
- The companion browser starts hidden and attempts Win32 child docking. Floating mode is only a recovery path after a native docking failure.
- Blocking I/O is delegated to worker threads and the UI drains events. Source modules stay importable without desktop dependencies on non-Windows systems.

Implementation and test findings are appended below as modules are integrated.

## Integration fixes and evidence

- Canonical parser: 227 isolated regression cases pass, including repaired control characters, bidi handling with ZWNJ preservation, broken-fence rescue, naked-root errors, DSML variants and truncated parameters. All consumers use the Python parser; no extension code exists.
- Local backend: 104 isolated tests pass for rules/config, tree/files, safety, streaming terminal and Git. Git initially inherited globally forced ANSI color; subprocesses now force `color.ui=false` rather than weakening the diff test.
- Driver event draining initially assumed an array, but the agent returns `{ok,events}`. Adapted the consumer so page approval responses and scoped limits reach the desktop.
- Added `approvalDismiss`/`approval_closed` coordination so approving in the desktop does not leave a page modal blocking the composer.
- A read-chat response contains its own URL. The driver now merges it once rather than passing a duplicate URL keyword, which raised a Python error.
- Generic capture requires calling the page's `baseline()` before sending. The driver now arms that baseline before both the original send and the single permitted retry.
- Parsing the same no-ID tool request separately for display and dispatch created two UUIDs. The driver now parses once and attaches `parsed_calls` to the final event; the desktop reuses those IDs. Streams only sanitize text instead of creating repeated pending tool rows.
- `state_save` must honor the active chat's `project_path`, not overwrite it with the previous global project. It now restores each active workspace and reloads chat URLs on restart. Request owners retain workspace snapshots during concurrent UI changes.
- Failed terminal process creation must not wait forever for an exit code. The terminal yields exit -1 and the executor watches the `running` flag.
- pywebview promise evaluation uses a callback and a bounded wait. Native scripts run only in daemon workers. A hung native evaluate call gates subsequent evaluations instead of leaking an unbounded number of evaluation threads.
- Web navigation prefers the live sidebar link for a same-origin conversation; full native navigation is the fallback. Multiple tool-result attachments are uploaded only after ensuring the correct owning conversation and waiting for idle.

The shipped validation report records final combined checks and explicitly separates synthetic Chromium evidence from untested native Windows and signed-in service behavior.

## Final security and lifecycle review

A read-only integration review found four issues that mock happy paths did not cover. They were corrected before source delivery and new regressions were added.

1. The original proposal allowed approving local actions inside the remote website. That page can synthesize clicks, call `approvalDismiss`, or replace `drain()`; it cannot be an authorization boundary. The implementation now permits approvals only through the desktop Api card. The RTL page overlay displays status and can deny, but its affirmative responses are ignored. This is safer than two-location approval and is an explicit deliberate deviation from that proposal.
2. Provider calls sent complete external-client transcripts into whichever same-site web chat happened to be open. Provider requests now carry `fresh: true`; the driver forces a fresh home/new-conversation navigation so private desktop context is not inherited.
3. Page-idle and intermediate tool-bearing assistant responses cleared the request's Stop state while commands/approvals were pending. Final assistant packets now carry `continuation_pending`; UI request lifecycle stays busy until the no-tool final response or stop/failure, independently of page-idle flips. A new Playwright group checks this.
4. Stopping a queued request called Stop on the active page, and Api/WS paths duplicated the stop. Cancellation now follows one WS dispatch, records a request-specific stopped marker, and invokes page Stop only for the active owner. Native evaluation checks ownership again immediately before the script executes, so a delayed worker cannot stop a subsequent turn.

Additional regressions cover forged remote approval, fresh Provider navigation, queued-request stop isolation, late native stop ownership, single stop dispatch, and ignored stopped heartbeats. Windows native behavior and real signed-in site acceptance remain unverified.

## Source handoff

Final source checks: 365 pytest tests passed without warnings; 47/47 Chromium page-agent cases and 15 UI groups passed. Python compilation, JavaScript syntax, version synchronization and DOM pins passed. The final added queued-stop regression ensures an already-cancelled queued turn never replaces the active owner. A bounded page-stop completion event keeps ownership until the stop attempt finishes, avoiding the capture/native-stop race.

The ZIP includes source, runtime/development requirements, Windows launcher, PyInstaller/Inno build recipes, application icon, English/Persian documentation, original specification, protocol, automated tests, UI preview and actual validation outputs. It excludes environments, caches, user state, databases, secrets and native build outputs. A SHA-256 source manifest is included.

Not completed in this environment: Windows executable/installer production and installed-app launch; real HWND/DPI WebView2 docking; persistence of signed-in real accounts across native restarts; live-site acceptance for the five services and custom sites. These are explicit remaining acceptance tasks, not reported as successful.

## Windows pywebview recursion fix

The user's frozen EXE reproduced pywebview's `AccessibilityObject.Bounds.Empty... maximum recursion depth exceeded` loop. The cause was `api.window = window`: pywebview walks public js_api attributes while creating the WinForms accessibility bridge, and a public native Window object recursively exposes its AccessibilityObject. This matches pywebview issue #1815. The field is now `_window`; file-dialog methods and startup use the private name, and a regression test asserts that `window` is not in Api.__dict__. The user must rebuild the EXE because the existing dist executable still contains the old code.

The next user trace changed the path to `browser.main_window.native.HorizontalScroll.ParentControl.ModifierKeys`, proving that the first private `_window` fix was not enough: `Api.browser` still exposed InternalBrowser and its native main_window to pywebview. Api now stores both native references as `_window` and `_browser`; application methods and startup wiring were updated, and tests assert neither public `window` nor `browser` exists in Api.__dict__. The existing EXE must be rebuilt again.
