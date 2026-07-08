# Build ELI v2 Windows Setup.exe (Inno Setup) from the lean portable zip.
# Run ON WINDOWS with Inno Setup 6 installed (iscc.exe on PATH).
#
#   powershell -ExecutionPolicy Bypass -File packaging\windows\build-windows.ps1 -Version 2.0.9
param(
    [string]$Version = "",
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"
if (-not $ProjectRoot) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}
Set-Location $ProjectRoot

if (-not $Version) {
    $Version = (Select-String -Path "pyproject.toml" -Pattern '^version' | Select-Object -First 1).Line -replace '.*"(.*)".*','$1'
}

$Dist = Join-Path $ProjectRoot "dist"
$Staging = Join-Path $ProjectRoot "build\win-portable\ELI_v2-$Version-windows-portable"
$Zip = Join-Path $Dist "ELI_v2-$Version-windows-portable.zip"

if (-not (Test-Path $Zip)) {
    Write-Host "[windows] portable zip missing — run: bash build_packages.sh windows-lean"
    if (Get-Command bash -ErrorAction SilentlyContinue) {
        bash build_packages.sh windows-lean
    } else {
        throw "Missing $Zip — build the windows-lean zip first."
    }
}

Write-Host "[windows] extracting $Zip"
if (Test-Path $Staging) { Remove-Item -Recurse -Force $Staging }
New-Item -ItemType Directory -Force -Path (Split-Path $Staging) | Out-Null
Expand-Archive -Path $Zip -DestinationPath (Split-Path $Staging) -Force

# Grandma-friendly setup launcher (double-click, no PowerShell policy fuss for end users)
$SetupBat = Join-Path $Staging "ELI_Setup.bat"
@'
@echo off
title ELI Setup
cd /d "%~dp0"
echo.
echo  ELI v2.0 — one-click setup
echo  This may take several minutes the first time.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Yes
if errorlevel 1 (
  echo.
  echo Setup failed. Try running install.bat manually.
  pause
  exit /b 1
)
echo.
echo Setup complete. Use eli.bat or the Start Menu shortcut to launch ELI.
pause
'@ | Set-Content -Path $SetupBat -Encoding ASCII

# Copy icon tree for Inno
$IconSrc = Join-Path $ProjectRoot "packaging\desktop\Eli_Icon.png"
if (Test-Path $IconSrc) {
    $IconDst = Join-Path $Staging "packaging\desktop"
    New-Item -ItemType Directory -Force -Path $IconDst | Out-Null
    Copy-Item $IconSrc $IconDst -Force
}

$Iscc = $null
foreach ($c in @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "iscc"
)) {
    if ($c -eq "iscc") {
        if (Get-Command iscc -ErrorAction SilentlyContinue) { $Iscc = "iscc"; break }
    } elseif (Test-Path $c) { $Iscc = $c; break }
}

$Iss = Join-Path $ProjectRoot "packaging\windows\ELI_Setup.iss"
$OutExe = Join-Path $Dist "ELI_v2-$Version-Setup.exe"

if (-not $Iscc) {
    Write-Warning "[windows] Inno Setup (iscc) not found."
    Write-Host "[windows] Grandma-friendly fallback ready:"
    Write-Host "  Extract: $Zip"
    Write-Host "  Double-click: ELI_Setup.bat"
    exit 0
}

Write-Host "[windows] compiling $OutExe"
& $Iscc $Iss "/DMyAppVersion=$Version"
if (Test-Path $OutExe) {
    $hash = (Get-FileHash $OutExe -Algorithm SHA256).Hash.ToLower()
    "$hash  $(Split-Path $OutExe -Leaf)" | Set-Content "$OutExe.sha256"
    Write-Host "[windows] complete: $OutExe"
} else {
    throw "Inno Setup did not produce $OutExe"
}
