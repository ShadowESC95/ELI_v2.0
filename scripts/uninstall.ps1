# ELI uninstaller (Windows) -- removes the Start Menu shortcuts, the launcher and the install
# pointer this install added, and, optionally, the whole install folder. ELI is portable: all
# data lives under the install folder, so there is nothing in the registry or the cloud to clean up.
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
    $all = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    # This script and the processes that started it (UNINSTALL.bat's console, the Start Menu
    # launcher) name this folder too: stopping them ended the uninstall before it removed anything.
    $own = @()
    $cur = $PID
    while ($cur -and ($own -notcontains $cur)) {
        $own += $cur
        $mine = $all | Where-Object { $_.ProcessId -eq $cur } | Select-Object -First 1
        $cur = if ($mine) { $mine.ParentProcessId } else { 0 }
    }
    $procs = $all | Where-Object {
        ($own -notcontains $_.ProcessId) -and (
            ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase)) -or
            ($_.CommandLine -and $_.CommandLine.Contains($Root)))
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

# What the install added outside this folder (install_desktop_apps.ps1, through
# eli.runtime.desktop_launchers): the Start Menu shortcuts named below, the launcher they start,
# %LOCALAPPDATA%\ELI_v2\eli-run.cmd, and the install pointer that launcher reads,
# %LOCALAPPDATA%\ELI_v2\runtime\install_root. Every ELI v2 install writes the same ones, so they
# belong to the install the pointer names: removed when it names this folder (or a folder that is
# gone, or there is none), left for the other ELI v2 install it names. A shortcut goes only when it
# starts that launcher or a file in this folder: ELI v3 uses some of the same names.
$Share = Join-Path $env:LOCALAPPDATA "ELI_v2"
$Launcher = Join-Path $Share "eli-run.cmd"
$Pointer = Join-Path $Share "runtime\install_root"
function Get-FullPath([string]$Path) {
    try { return [System.IO.Path]::GetFullPath($Path.Trim()).TrimEnd('\') } catch { return $Path.Trim().TrimEnd('\') }
}
$Pointed = $null
if (Test-Path -LiteralPath $Pointer) {
    # written as UTF-8 by desktop_launchers; Windows PowerShell reads a file without a BOM as ANSI
    $Pointed = "$(@(Get-Content -LiteralPath $Pointer -Encoding UTF8 -TotalCount 1)[0])".Trim()
}
$Mine = (-not $Pointed) -or ((Get-FullPath $Pointed) -eq (Get-FullPath $Root)) -or (-not (Test-Path -LiteralPath $Pointed))

$Shell = $null
try { $Shell = New-Object -ComObject WScript.Shell } catch { $Shell = $null }
foreach ($n in @("ELI v2.0.lnk","ELI Server (Web App).lnk","ELI Uninstall.lnk","ELI Setup.lnk","ELI Pro.lnk")) {
    $lnk = Join-Path $Programs $n
    if (-not (Test-Path -LiteralPath $lnk)) { continue }
    $Target = ""
    if ($Shell) { try { $Target = "$($Shell.CreateShortcut($lnk).TargetPath)" } catch { $Target = "" } }
    $Inside = $Target -and (Get-FullPath $Target).StartsWith((Get-FullPath $Root) + "\", [System.StringComparison]::OrdinalIgnoreCase)
    if ($Inside -or ($Mine -and ((Get-FullPath $Target) -eq (Get-FullPath $Launcher)))) {
        Remove-Item -Force -LiteralPath $lnk
        Write-Host "  [OK] Removed the Start Menu shortcut $n"
    }
}
if ($Mine) {
    foreach ($f in @($Launcher, $Pointer)) { Remove-Item -Force -LiteralPath $f -ErrorAction SilentlyContinue }
    # Their folders only when that leaves them empty: the installed app keeps its data in ELI_v2.
    foreach ($d in @((Join-Path $Share "runtime"), $Share)) {
        try { [System.IO.Directory]::Delete($d, $false) } catch { Write-Verbose "kept $d (not empty, or gone)" }
    }
    Write-Host "  [OK] Removed ELI v2's launcher (eli-run.cmd) and install pointer."
} else {
    Write-Host "  [kept] ELI v2's launcher, install pointer and the shortcuts that start it: they belong to"
    Write-Host "         the ELI v2 install at $Pointed"
}

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
