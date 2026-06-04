; Inno Setup installer for Gateway (Windows)
; CI 调用:ISCC.exe /DGatewayVersion=0.1.4 installer\gateway.iss
; 产物:installer\Output\Gateway-Setup-{version}-x64.exe
;
; 设计原则:
;   - 装到 %LOCALAPPDATA%\Gateway,不要求 admin (PrivilegesRequired=lowest)
;   - 开始菜单 + 卸载注册到控制面板,无桌面图标默认(用户勾才装)
;   - vault / config / state 仍走应用自己的 %APPDATA%\HumanAI 路径,
;     卸载只删 install dir,不动用户数据

#define GatewayName "Gateway"
#ifndef GatewayVersion
  #define GatewayVersion "0.0.0-dev"
#endif

[Setup]
; 固定 AppId GUID — 升级时认这个 ID 而非 AppName/Version
AppId={{4A6B7C8D-9E10-4F11-A234-B567C8D9E0F1}
AppName={#GatewayName}
AppVersion={#GatewayVersion}
AppPublisher=yang chunyan
AppPublisherURL=https://github.com/Huangleyang125207/human-ai-gateway
AppSupportURL=https://github.com/Huangleyang125207/human-ai-gateway/issues
AppUpdatesURL=https://gateway.yanpaidb.cn/

DefaultDirName={localappdata}\Gateway
DefaultGroupName={#GatewayName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

OutputDir=Output
OutputBaseFilename=Gateway-Setup-{#GatewayVersion}-x64

Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

UninstallDisplayName={#GatewayName}
UninstallDisplayIcon={app}\Gateway.exe

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; PyInstaller onedir 输出在 ..\dist-pyinstaller\Gateway\
; 整个文件夹原样拷,包含 Gateway.exe + _internal/ 依赖
Source: "..\dist-pyinstaller\Gateway\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#GatewayName}"; Filename: "{app}\Gateway.exe"
Name: "{group}\Uninstall {#GatewayName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#GatewayName}"; Filename: "{app}\Gateway.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Gateway.exe"; Description: "{cm:LaunchProgram,{#GatewayName}}"; Flags: nowait postinstall skipifsilent
