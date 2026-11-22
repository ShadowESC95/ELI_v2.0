{ Shared by installer.iss and ELI_Setup.iss: #include "eli_launchers.iss" in their [Code] section,
  then RemoveEliLaunchers(<the folder ELI runs from>) once Setup's own files are uninstalled.

  What ELI adds outside the folders Setup installs (eli.runtime.desktop_launchers, which a source
  install runs, and which the installed app ran on every start up to 2.5.36): Start Menu shortcuts
  that start %LOCALAPPDATA%\ELI_v2\eli-run.cmd, that launcher, and the install pointer it reads,
  %LOCALAPPDATA%\ELI_v2\runtime\install_root. Every ELI v2 install writes the same ones, so they
  belong to the install the pointer names: with it naming Root (or a folder that is gone, or with no
  pointer) they are removed, and with it naming another ELI v2 install they are left for that one.
  A shortcut goes only when it starts that launcher or a file in Root: ELI v3 uses some of the same
  names. The folders go only when that leaves them empty: the installed app keeps its data in ELI_v2.
  scripts\uninstall.ps1 does the same for a portable install. }

function EliFullPath(const Path: String): String;
begin
  Result := RemoveBackslashUnlessRoot(ExpandFileName(Trim(Path)));
end;

function EliSamePath(const A, B: String): Boolean;
begin
  Result := (Trim(A) <> '') and (CompareText(EliFullPath(A), EliFullPath(B)) = 0);
end;

function EliInside(const Path, Folder: String): Boolean;
var
  Prefix: String;
begin
  Prefix := AddBackslash(EliFullPath(Folder));
  Result := (Trim(Path) <> '') and (CompareText(Copy(EliFullPath(Path), 1, Length(Prefix)), Prefix) = 0);
end;

function EliShortcutTarget(const Lnk: String): String;
var
  Shell, Link: Variant;
begin
  Result := '';
  try
    Shell := CreateOleObject('WScript.Shell');
    Link := Shell.CreateShortcut(Lnk);
    Result := Link.TargetPath;
  except
    Log('Could not read where ' + Lnk + ' points: ' + GetExceptionMessage);
  end;
end;

procedure RemoveEliLaunchers(const Root: String);
var
  Share, Launcher, Pointer, Pointed, Lnk, Target: String;
  Lines, Names: TArrayOfString;
  Mine: Boolean;
  I: Integer;
begin
  Share := ExpandConstant('{localappdata}\ELI_v2');
  Launcher := Share + '\eli-run.cmd';
  Pointer := Share + '\runtime\install_root';
  Pointed := '';
  if LoadStringsFromFile(Pointer, Lines) then
    if GetArrayLength(Lines) > 0 then
      Pointed := Trim(Lines[0]);
  Mine := True;
  if Pointed <> '' then
    Mine := EliSamePath(Pointed, Root) or not DirExists(Pointed);

  { the names eli.runtime.desktop_launchers.windows_shortcuts() gives, and two older ones }
  SetArrayLength(Names, 5);
  Names[0] := 'ELI v2.0.lnk';
  Names[1] := 'ELI Server (Web App).lnk';
  Names[2] := 'ELI Uninstall.lnk';
  Names[3] := 'ELI Setup.lnk';
  Names[4] := 'ELI Pro.lnk';
  for I := 0 to GetArrayLength(Names) - 1 do
  begin
    Lnk := ExpandConstant('{userprograms}\') + Names[I];
    if FileExists(Lnk) then
    begin
      Target := EliShortcutTarget(Lnk);
      if EliInside(Target, Root) or (Mine and EliSamePath(Target, Launcher)) then
        if DeleteFile(Lnk) then
          Log('Removed the Start Menu shortcut ' + Lnk);
    end;
  end;

  if not Mine then
  begin
    Log('ELI v2''s launcher and install pointer belong to the install at ' + Pointed + ': left in place');
    Exit;
  end;
  if DeleteFile(Launcher) then
    Log('Removed ' + Launcher);
  if DeleteFile(Pointer) then
    Log('Removed ' + Pointer);
  RemoveDir(Share + '\runtime');
  RemoveDir(Share);
end;
