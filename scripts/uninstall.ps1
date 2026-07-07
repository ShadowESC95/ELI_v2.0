# ELI uninstaller (Windows) — removes Start Menu shortcuts and, optionally, the whole
# install folder. ELI is portable: all data lives under the install folder, so there is
# nothing in the registry or the cloud to clean up.
$ErrorActionPreference = "SilentlyContinue"
$Root = Split-Path -Parent $PSScriptRoot      # scripts\.. = install root
$Programs = [Environment]::GetFolderPath("Programs")

Write-Host "ELI uninstaller"
Write-Host "  Install folder: $Root"
Write-Host ""

foreach ($n in @("ELI v2.0.lnk","ELI Server (Web App).lnk","ELI Setup.lnk","ELI Uninstall.lnk","ELI Pro.lnk")) {
    Remove-Item -Force -Path (Join-Path $Programs $n) -ErrorAction SilentlyContinue
}
Write-Host "  [OK] Removed ELI Start Menu shortcuts."

Write-Host ""
Write-Host "  Your data (chats, memory, models) lives under: $Root"
$ans = Read-Host "  Delete the ENTIRE install folder (all data + models)? [y/N]"
if ($ans -eq "y" -or $ans -eq "Y") {
    Set-Location $env:USERPROFILE
    Remove-Item -Recurse -Force -Path $Root
    Write-Host "  [OK] ELI fully removed."
} else {
    Write-Host "  [kept] Delete the folder manually anytime: $Root"
}
Write-Host ""
Write-Host "Done. ELI was 100% local - nothing was ever stored in the cloud to remove."
