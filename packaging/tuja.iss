#define MyAppName "투자"
#define MyAppVersion "0.9.0-beta"
#define MyAppPublisher "Dr-Silvan"
#define MyAppExeName "투자.exe"

[Setup]
AppId={{8C27DCA6-76DA-4C82-A21C-9A9EB52CB508}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\투자
DefaultGroupName=투자
PrivilegesRequired=lowest
OutputDir=..\release
OutputBaseFilename=Tuja-Setup-0.9.0-beta
SetupIconFile=..\assets\tuja-icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
VersionInfoVersion=0.9.0.0
VersionInfoProductName=투자
VersionInfoDescription=Local-first trading workstation
LicenseFile=..\LICENSE

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕 화면에 투자 바로가기 만들기"; GroupDescription: "추가 바로가기:"; Flags: checkedonce

[Files]
Source: "..\dist\투자\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\PRIVACY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\SECURITY.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\투자"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\투자"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "투자 실행"; Flags: nowait postinstall skipifsilent
