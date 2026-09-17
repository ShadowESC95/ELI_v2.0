# ELI uninstaller (Windows) -- removes Start Menu shortcuts and, optionally, the whole
# install folder. ELI is portable: all data lives under the install folder, so there is
# nothing in the registry or the cloud to clean up.
$ErrorActionPreference = "SilentlyContinue"
$Root = Split-Path -Parent $PSScriptRoot      # scripts\.. = install root
$Programs = [Environment]::GetFolderPath("Programs")

Write-Host "ELI uninstaller"
Write-Host "  Install folder: $Root"
Write-Host ""

# Stop any ELI instance running FROM THIS install first -- otherwise its
# background daemon (server / proactive / autonomy) keeps files open and
# Remove-Item below just fails with an access-denied error instead of
# deleting. Scoped to this Root so other ELI installs are untouched. Same
# reasoning as eli_uninstall.sh's _stop_running on Linux/macOS.
Write-Host "Checking for a running ELI (server/desktop) from this install..."
try {
    $procs = Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase)) -or
        ($_.CommandLine -and $_.CommandLine.Contains($Root))
    }
    if ($procs) {
        foreach ($p in $procs) {
            Write-Host "  Stopping running ELI process (PID $($p.ProcessId)): $($p.Name)"
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 2
        Write-Host "  [OK] Stopped."
    } else {
        Write-Host "  [OK] No running ELI instance from this install."
    }
} catch {
    Write-Host "  [WARN] Could not check for running ELI processes -- close ELI manually if the delete below fails."
}
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
