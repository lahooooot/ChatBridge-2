#define MyAppVersion "2.60.0"
#define MyAppName "ChatBridge"
#define MyAppExeName "ChatBridge-" + MyAppVersion + ".exe"

[Setup]
AppId={{5F52D2CB-3B91-4A80-B3E3-82E0E5255000}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=ChatBridge
DefaultDirName={localappdata}\Programs\ChatBridge
DefaultGroupName=ChatBridge
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=installer-output
OutputBaseFilename=ChatBridge-Setup-{#MyAppVersion}
SetupIconFile=icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion
Source: "README.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "docs\INSTALL.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\ChatBridge"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\ChatBridge"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch ChatBridge"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
var Version: String;
begin
  Result := True;
  if not RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and
     not RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) then
    Result := MsgBox('Microsoft WebView2 Runtime was not detected. ChatBridge requires it. Install the Evergreen WebView2 Runtime from Microsoft before launching. Continue installing ChatBridge?', mbConfirmation, MB_YESNO) = IDYES;
end;
