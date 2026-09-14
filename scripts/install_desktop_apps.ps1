# Install Start Menu shortcuts (Windows). Redistribution-safe: shortcuts call a
# stable %LOCALAPPDATA%\ELI_v2\eli-run.cmd that reads the install-root pointer —
# never a versioned extract folder path.
# Run:  powershell -ExecutionPolicy Bypass -File scripts\install_desktop_apps.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }
$env:PYTHONPATH = $Root
$env:ELI_PROJECT_ROOT = $Root
& $Py -m eli.runtime.desktop_launchers install --root $Root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
