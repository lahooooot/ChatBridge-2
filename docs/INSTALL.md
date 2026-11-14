# Installing ChatBridge

This page is for people who want to **install and use** ChatBridge.
If you want to build it from source, see the build section of [README.md](../README.md).

## Requirements

- Windows 10 or later (64-bit)
- [Microsoft Edge WebView2 Runtime](https://go.microsoft.com/fwlink/p/?LinkId=2124703)
  — already installed on most up-to-date Windows systems. The installer
  warns you if it is missing; install it from Microsoft and run the
  installer again.

No administrator rights are required. ChatBridge installs per-user.

## Install (recommended)

1. Open the [latest release](https://github.com/lahooooot/ChatBridge-2/releases/latest).
2. Download **`ChatBridge-Setup-X.Y.Z.exe`** (for example `ChatBridge-Setup-2.50.0.exe`).
3. Double-click the file.
4. Windows SmartScreen may show a warning because the build is not signed.
   Click **More info → Run anyway**.
5. Follow the wizard. When it finishes, ChatBridge starts automatically.
   You can launch it later from the Start Menu shortcut, or from the
   optional desktop shortcut.

Where it installs:

| Item | Location |
|------|----------|
| Program files | `%LOCALAPPDATA%\Programs\ChatBridge` |
| Start Menu shortcut | Start Menu → ChatBridge |
| Your data (config, logs, WebView2 profile) | `%USERPROFILE%\.chatbridge-2.60.0` |

## Portable option (no installation)

If you do not want to install anything:

1. Download **`ChatBridge-X.Y.Z.exe`** from the same release page.
2. Put it anywhere you like.
3. Double-click it to run.

Portable mode uses the same `%USERPROFILE%\.chatbridge-2.60.0` folder for
its data, so switching between portable and installed builds keeps your
settings.

## Verify your download (optional)

Each release includes a `SHA256SUMS.txt` file with the hash of every
asset. To check that your download is intact, open PowerShell in the
folder containing the installer and run:

```powershell
Get-FileHash .\ChatBridge-Setup-X.Y.Z.exe -Algorithm SHA256
```

Compare the printed hash with the matching line in `SHA256SUMS.txt`.
They must be identical (case-insensitive).

## Upgrade to a newer version

Run the new installer over the old one. It replaces the program files
and keeps your data in `%USERPROFILE%\.chatbridge-2.60.0` untouched.

To keep two versions side by side, use the portable executable for the
second copy.

## Uninstall

Windows Settings → Apps → Installed apps → ChatBridge → Uninstall.

Uninstalling removes the program files and shortcuts. Your data folder
`%USERPROFILE%\.chatbridge-2.60.0` is **kept on purpose** so a reinstall
picks up where you left off. Delete that folder by hand if you want a
clean slate.

## Troubleshooting

**"Windows protected your PC"** — the build is not code-signed. Click
**More info → Run anyway**.

**"WebView2 Runtime was not detected"** — install the runtime from
https://go.microsoft.com/fwlink/p/?LinkId=2124703 and re-run the
installer.

**App opens but the internal browser stays blank** — open Settings →
Internal Browser → Clear profile, then reopen the browser. This signs
you out of the web chat service, so sign in again.

**Antivirus flags the executable** — PyInstaller builds are sometimes
false-flagged. If you do not trust the download, build from source
(see README.md) instead.

## Where to get help

Open an issue at https://github.com/lahooooot/ChatBridge-2/issues and
include your version (Settings → General), your Windows version, and a
short description of the problem.
