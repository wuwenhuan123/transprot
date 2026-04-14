#ifndef RepoRoot
#define RepoRoot ".."
#endif
#ifndef DistDir
#define DistDir AddBackslash(RepoRoot) + "dist\\TransProt"
#endif
#ifndef OutputDir
#define OutputDir AddBackslash(RepoRoot) + "installer-output"
#endif
#ifndef OutputBaseFilename
#define OutputBaseFilename "TransProt-Setup"
#endif

#define MyAppName "TransProt"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "TransProt"
#define MyAppExeName "TransProt.exe"

[Setup]
AppId={{8E7D6E4B-6D9D-4D0C-9F1B-1E6A7A5E4F01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
