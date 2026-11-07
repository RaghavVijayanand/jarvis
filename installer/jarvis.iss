; JARVIS for Windows — Inno Setup 6 script.
; Built by: python build\build_installer.py   (or: ISCC installer\jarvis.iss after PyInstaller)
; Installs per user by default (no admin prompt); the first page lets you choose all users instead.

#ifndef AppVersion
  #define AppVersion "3.1.0"
#endif
#define AppName "JARVIS"
#define AppExe "JARVIS.exe"

[Setup]
AppId={{6E2B6C4E-5A71-4C2E-9F0B-7A1D3E9C4B21}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=JARVIS
DefaultDirName={autopf}\JARVIS
DefaultGroupName=JARVIS
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=JARVIS-Setup-{#AppVersion}
SetupIconFile=..\assets\jarvis.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
; The running app holds this mutex, so setup and uninstall can ask to close it first.
AppMutex=JARVIS-Assistant-Mutex
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startup"; Description: "Start JARVIS when I sign in to Windows (it waits in the tray)"; GroupDescription: "Startup:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\JARVIS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\JARVIS"; Filename: "{app}\{#AppExe}"; Comment: "Your desktop assistant"
Name: "{autoprograms}\JARVIS dashboard"; Filename: "{app}\{#AppExe}"; Parameters: "--dashboard"
Name: "{autodesktop}\JARVIS"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Same value the app's own "Start with Windows" switch writes (core/autostart.py).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "JARVIS"; \
    ValueData: """{app}\{#AppExe}"" --tray"; Tasks: startup; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "JARVIS"; \
    Flags: dontcreatekey uninsdeletevalue

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch JARVIS now"; Flags: nowait postinstall skipifsilent

[Messages]
FinishedLabel=JARVIS is installed. It lives in the system tray: press Ctrl+Shift+Space to ask, or hold Ctrl+Alt and talk.

[Code]
// Settings, memory and reminders live in %APPDATA%\Jarvis. Offer to remove them on uninstall.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\Jarvis');
    if DirExists(DataDir) then
      if MsgBox('Also delete your JARVIS settings, memory and reminders?' + #13#10 + DataDir,
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
