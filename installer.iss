[Setup]
AppName=Jarvis AI (Safe)
AppVersion=1.0.0
DefaultDirName={autopf}\JarvisAI
DefaultGroupName=Jarvis AI
OutputDir=dist
OutputBaseFilename=JarvisAI-Installer
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "dist\JarvisAI.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Jarvis AI"; Filename: "{app}\JarvisAI.exe"
Name: "{commondesktop}\Jarvis AI"; Filename: "{app}\JarvisAI.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"
