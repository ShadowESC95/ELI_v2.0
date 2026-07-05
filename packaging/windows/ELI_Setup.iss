; Inno Setup script — grandma-friendly Windows installer for ELI v2 portable.
; Build on Windows: iscc packaging\windows\ELI_Setup.iss /DMyAppVersion=2.0.7
; Or: powershell -File packaging\windows\build-windows.ps1 -Version 2.0.7

#define MyAppName "ELI v2.0"
#define MyAppPublisher "ShadowESC95"
#define MyAppURL "https://github.com/ShadowESC95/ELI_v2.0"
#ifndef MyAppVersion
  #define MyAppVersion "2.0.7"
#endif

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\ELI_v2
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputBaseFilename=ELI_v2-{#MyAppVersion}-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\..\packaging\desktop\Eli_Icon.png
UninstallDisplayIcon={app}\packaging\desktop\Eli_Icon.png

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Files]
Source: "..\..\build\win-portable\ELI_v2-{#MyAppVersion}-windows-portable\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\eli.bat"; WorkingDir: "{app}"; IconFilename: "{app}\packaging\desktop\Eli_Icon.png"
Name: "{group}\ELI Setup (repair)"; Filename: "{app}\ELI_Setup.bat"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\eli.bat"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\packaging\desktop\Eli_Icon.png"

[Run]
Filename: "{app}\ELI_Setup.bat"; Description: "Set up ELI now (recommended)"; Flags: postinstall nowait skipifsilent
Filename: "{app}\eli.bat"; Description: "Launch ELI"; Flags: postinstall nowait skipifsilent unchecked

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
