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

#ifndef PluginRuntime
#define PluginRuntime "dist\plugin-runtime"
#endif

#ifndef WebView2Bootstrapper
#define WebView2Bootstrapper "dist\MicrosoftEdgeWebview2Setup.exe"
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
OutputBaseFilename=OmniWatch-windows-{#Architecture}-setup-v{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
UninstallDisplayIcon={app}\pico-monitor.exe
#if Architecture == "x64"
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#endif

[Languages]
; 将简体中文翻译随源码发布，避免 CI 构建机未安装外部语言包时编译失败。
Name: "chinesesimplified"; MessagesFile: "packaging\languages\ChineseSimplified.isl"

[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; DestName: "pico-monitor.exe"; Flags: ignoreversion
Source: "{#PluginRuntime}\*"; DestDir: "{app}\plugin-runtime"; Flags: ignoreversion recursesubdirs createallsubdirs
; Bootstrapper 仅在安装阶段使用，安装结束后由 Inno Setup 清理临时文件。
Source: "{#WebView2Bootstrapper}"; DestDir: "{tmp}"; DestName: "MicrosoftEdgeWebview2Setup.exe"; Flags: deleteafterinstall

[Icons]
Name: "{group}\OmniWatch Monitor"; Filename: "{app}\pico-monitor.exe"
Name: "{autodesktop}\OmniWatch Monitor"; Filename: "{app}\pico-monitor.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "正在安装 Microsoft Edge WebView2 Runtime..."; Flags: waituntilterminated; Check: not IsWebView2RuntimeInstalled
Filename: "{app}\pico-monitor.exe"; Description: "启动 OmniWatch Monitor"; Flags: nowait postinstall skipifsilent runascurrentuser

[Code]
const
  WebView2ClientKey = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

{ 判断指定注册表位置是否包含有效的 WebView2 Runtime 版本。 }
function HasUsableWebView2Version(RootKey: Integer; const ClientKey: String): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(RootKey, ClientKey, 'pv', Version) and
    (Trim(Version) <> '') and (CompareText(Trim(Version), '0.0.0.0') <> 0);
end;

{ 检查用户级或机器级 WebView2 Runtime 是否已经安装。 }
function IsWebView2RuntimeInstalled(): Boolean;
begin
  { WebView2 的机器级注册信息位于 32 位注册表视图，用户级安装位于 HKCU。 }
  Result := HasUsableWebView2Version(HKCU, WebView2ClientKey) or
    HasUsableWebView2Version(HKLM32, WebView2ClientKey);
end;
