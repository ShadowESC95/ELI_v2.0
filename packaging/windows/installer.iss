; ELI v2 - Windows installer for the PyInstaller (frozen) build.
;
; Wraps the one-dir bundle produced by `pyinstaller ELI.spec` (dist\ELI\).
; The legacy packaging\windows\ELI_Setup.iss wraps the source-portable zip
; and is intentionally left untouched.
;
; Build (version is REQUIRED and comes from pyproject.toml / the CI tag):
;   iscc packaging\windows\installer.iss /DMyAppVersion=2.1.0
;
; Installs per-user to {localappdata}\Programs\ELI (no admin rights). The
; bundle directory is user-writable, so the frozen runtime hook keeps all
; settings/models/artifacts beside the app - and Inno's uninstaller only
; removes files it installed, so downloaded models and user data survive
; an uninstall.

#ifndef MyAppVersion
  #pragma error "MyAppVersion not defined - build with: iscc installer.iss /DMyAppVersion=<version from pyproject.toml>"
#endif

#define MyAppName "ELI v2.0"
#define MyAppExeName "ELI.exe"
#define MyAppPublisher "ShadowESC95"
#define MyAppURL "https://github.com/ShadowESC95/ELI_v2.0"
#define BundleDir "..\..\dist\ELI"

#if !FileExists(BundleDir + "\" + MyAppExeName)
  #pragma error "dist\ELI\ELI.exe not found - run `pyinstaller --noconfirm ELI.spec` first"
#endif

[Setup]
AppId={{7E1D9F5C-4B2A-4D3E-9C8F-2A6B5E0D7F41}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\ELI
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename=ELI-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\desktop\Eli_Icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}
VersionInfoPublisher={#MyAppPublisher}
VersionInfoDescription=ELI v2.0 - Local AI Assistant

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch ELI"; Flags: postinstall nowait skipifsilent
