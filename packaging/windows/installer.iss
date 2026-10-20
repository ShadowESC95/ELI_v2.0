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
#define MyServerExeName "ELI-Server.exe"
#define MyAppPublisher "ShadowESC95"
#define MyAppURL "https://github.com/ShadowESC95/ELI_v2.0"
#define BundleDir "..\..\dist\ELI"

#if !FileExists(BundleDir + "\" + MyAppExeName)
  #pragma error "dist\ELI\ELI.exe not found - run `pyinstaller --noconfirm ELI.spec` first"
#endif

; ELI is source-available under PolyForm Noncommercial, so the installer must put
; the terms in front of the user before anything is written to disk. LICENSE.txt
; is a generated UTF-8+BOM copy of LICENSE - Inno decodes a BOM-less UTF-8 file
; as ANSI and mangles the (c), em-dash and rule characters.
#if !FileExists("LICENSE.txt")
  #pragma error "packaging\windows\LICENSE.txt not found - run `python scripts\make_installer_license.py` first"
#endif

; Microsoft Visual C++ 2015-2022 runtime, required by llama.cpp and onnxruntime. Setup runs without
; admin rights and this installer needs them, so it only runs when the machine lacks this version
; (most already have it), and it asks Windows for permission in front of Setup with its own
; progress window. Run with /quiet from a non-admin Setup, Windows' permission prompt could open
; behind the Setup window while Setup waited on it with no visible prompt, which looked like a
; hang ("gets to the C++ runtime at the very end and just hangs there").
#define VCRedist "..\..\build\vc_redist.x64.exe"
#if !FileExists(VCRedist)
  #pragma error "build\vc_redist.x64.exe not found - CI downloads it next to the bundle"
#endif
#define VCMajor 0
#define VCMinor 0
#define VCRev 0
#define VCBuild 0
#expr ParseVersion(VCRedist, VCMajor, VCMinor, VCRev, VCBuild)

[Setup]
AppId={{7E1D9F5C-4B2A-4D3E-9C8F-2A6B5E0D7F41}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppCopyright=Copyright (C) 2026 Jason Fitzgibbon Bridgeman. All rights reserved.
LicenseFile=LICENSE.txt
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
; Wizard branding. SetupIconFile only dresses the setup .exe itself — without these
; every page of the installer showed Inno's stock artwork, which is the first thing a
; new user sees of ELI. Must be 24-bit BMP (Inno rejects .png/.ico here); regenerate
; from the app icon with packaging\desktop\generate_wizard_images.py. The second entry
; in each list is the high-DPI variant, picked automatically by display scaling.
WizardImageFile=..\desktop\wizard_large.bmp,..\desktop\wizard_large_989.bmp
WizardSmallImageFile=..\desktop\wizard_small.bmp,..\desktop\wizard_small_138.bmp
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=ELI v2.0 - Local AI Assistant
; %TEMP%\Setup Log <date> #NNN.txt: what Setup did, for any report of a failed install
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce
; The GPU pack is not downloaded here: ELI offers it on first start for whichever GPU it finds
; (NVIDIA, AMD, Intel), with a progress window, and CPU mode works without it. A download inside
; Setup had no cancel and only covered NVIDIA.
; Game-save semantics: by default an upgrade KEEPS your settings/memory/models.
; Tick for a clean slate (models and GPU pack are kept — static downloads).
Name: "freshinstall"; Description: "Fresh install — reset ELI's settings and memory (keeps downloaded AI models)"; GroupDescription: "Existing data:"; Flags: unchecked; Check: HasExistingData

[InstallDelete]
; The frozen runtime is versioned as a whole: upgrading over an older install
; must never mix two PyInstaller trees (stale DLLs made llama.dll unloadable
; on upgraded machines). User data lives in {localappdata}\ELI_v2, not here.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Extracted and run only when the machine needs it (VCRuntimeNeeded, InstallVCRuntime below).
Source: "{#VCRedist}"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: VCRuntimeNeeded; \
  AfterInstall: InstallVCRuntime

[Code]
var
  VCRuntimeRestart: Boolean;

{ True unless the x64 Visual C++ 14 runtime is registered at the bundled version or newer.
  /VCRUNTIME=force on Setup's command line runs it regardless (CI uses it to exercise this path). }
function VCRuntimeNeeded: Boolean;
var
  Key: string;
  Installed, Major, Minor, Bld: Cardinal;
begin
  Key := 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64';
  Result := True;
  if CompareText(ExpandConstant('{param:VCRUNTIME|auto}'), 'force') = 0 then
    Log('Visual C++ runtime: forced from the command line')
  else if RegQueryDWordValue(HKLM64, Key, 'Installed', Installed) and (Installed = 1) and
     RegQueryDWordValue(HKLM64, Key, 'Major', Major) and
     RegQueryDWordValue(HKLM64, Key, 'Minor', Minor) and
     RegQueryDWordValue(HKLM64, Key, 'Bld', Bld) then
    Result := (Major < {#VCMajor}) or ((Major = {#VCMajor}) and
              ((Minor < {#VCMinor}) or ((Minor = {#VCMinor}) and (Bld < {#VCRev}))));
  Log(Format('Visual C++ runtime needed: %d (bundled {#VCMajor}.{#VCMinor}.{#VCRev})', [Ord(Result)]));
end;

{ Runs the runtime installer elevated through Windows' own permission prompt, with its progress
  window showing. Declining, or a failure, is said plainly; Setup never waits on something unseen. }
procedure InstallVCRuntime;
var
  Path: string;
  Code: Integer;
begin
  Path := ExpandConstant('{tmp}\vc_redist.x64.exe');
  if not FileExists(Path) then
    Exit;
  WizardForm.StatusLabel.Caption := 'Installing the Microsoft Visual C++ runtime (Windows will ask for permission)...';
  if not ShellExec('runas', Path, '/install /passive /norestart', '', SW_SHOW, ewWaitUntilTerminated, Code) then
  begin
    Log(Format('Visual C++ runtime installer did not start: %d %s', [Code, SysErrorMessage(Code)]));
    SuppressibleMsgBox('ELI needs the Microsoft Visual C++ runtime, and its installer did not run ('
      + SysErrorMessage(Code) + ').' + #13#10#13#10
      + 'ELI is installed. If it does not start, install "Microsoft Visual C++ Redistributable (x64)" '
      + 'from https://aka.ms/vs/17/release/vc_redist.x64.exe, or run this Setup again.',
      mbInformation, MB_OK, IDOK);
  end
  else
  begin
    Log(Format('Visual C++ runtime installer exit code: %d', [Code]));
    { 1638: a newer version is already installed; 3010: installed, restart needed }
    if Code = 3010 then
      VCRuntimeRestart := True
    else if (Code <> 0) and (Code <> 1638) then
      SuppressibleMsgBox(Format('The Microsoft Visual C++ runtime installer stopped with code %d.', [Code])
        + #13#10#13#10 + 'ELI is installed. If it does not start, install "Microsoft Visual C++ '
        + 'Redistributable (x64)" from https://aka.ms/vs/17/release/vc_redist.x64.exe.',
        mbInformation, MB_OK, IDOK);
  end;
end;

function NeedRestart: Boolean;
begin
  Result := VCRuntimeRestart;
end;

function HasExistingData: Boolean;
begin
  Result := DirExists(ExpandConstant('{localappdata}\ELI_v2'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Root: string;
begin
  { Fresh install: wipe settings/memory/artifacts BEFORE the app first runs.
    models/ and runtime/ (GPU pack) survive - static downloads, no state. }
  if (CurStep = ssInstall) and WizardIsTaskSelected('freshinstall') then
  begin
    Root := ExpandConstant('{localappdata}\ELI_v2');
    DelTree(Root + '\config', True, True, True);
    DelTree(Root + '\artifacts', True, True, True);
    DelTree(Root + '\eli', True, True, True);
    DelTree(Root + '\api', True, True, True);
    DelTree(Root + '\blueprints', True, True, True);
    DelTree(Root + '\docs', True, True, True);
    DelTree(Root + '\eli_docs', True, True, True);
    DeleteFile(Root + '\.eli_frozen_seed_version');
  end;
end;

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\ELI Server (phone and web)"; Filename: "{app}\{#MyServerExeName}"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
; Do NOT put ELI-Server on the desktop — users double-click both icons after
; install and get a second window / confused "two ELIs" report. Server stays
; in the Start Menu only.
Name: "{autodesktop}\Uninstall ELI"; Filename: "{uninstallexe}"; Tasks: desktopicon

[Run]
; Exactly one post-install GUI launch.
Filename: "{app}\{#MyAppExeName}"; Description: "Launch ELI"; Flags: postinstall nowait skipifsilent
