; Pico Monitor Windows 安装包脚本，负责把 PyInstaller 生成的 EXE 以标准安装方式发布。

#ifndef AppVersion
#define AppVersion "development"
#endif

#ifndef SourceExe
#define SourceExe "dist\pico-monitor.exe"
#endif

#ifndef Architecture
#define Architecture "x64"
#endif

[Setup]
AppId={{B7BA6741-67A0-4B49-89F2-5BC22215E90B}
AppName=OmniWatch Monitor
AppVersion={#AppVersion}
AppPublisher=OmniWatch
DefaultDirName={autopf}\OmniWatch Monitor
DefaultGroupName=OmniWatch Monitor
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=OmniWatch-windows-{#Architecture}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
UninstallDisplayIcon={app}\pico-monitor.exe
#if Architecture == "x64"
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#endif

[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; DestName: "pico-monitor.exe"; Flags: ignoreversion

[Icons]
Name: "{group}\OmniWatch Monitor"; Filename: "{app}\pico-monitor.exe"
Name: "{autodesktop}\OmniWatch Monitor"; Filename: "{app}\pico-monitor.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Run]
Filename: "{app}\pico-monitor.exe"; Description: "启动 OmniWatch Monitor"; Flags: nowait postinstall skipifsilent runascurrentuser