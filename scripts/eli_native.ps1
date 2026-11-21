# Invoke-Native: run a program and get back its exit code and what it printed.
#
# Windows PowerShell 5.1 turns each line a program writes to stderr, once that stream is
# redirected (2>$null, 2>&1, *>$null), into an error record, and while $ErrorActionPreference is
# "Stop" the first one ends the whole script, though the program goes on and succeeds: a warning
# printed during "import eli" stopped install.ps1. PowerShell 7.2 and newer leave a program's
# stderr out of the error preference. Here the preference is "Continue" in this function's own
# scope, so the calling script keeps "Stop" for everything else. A script that checks a program,
# or hides its output, goes through this function instead of redirecting the program's streams
# itself (tests/test_install_script.py scans the shipped scripts for one that does).
#
#   $r = Invoke-Native $Python @("-c", "import sys")
#   $r.ExitCode   the program's exit code; $null when it could not be started at all
#   $r.Output     what it wrote to stdout, one string per line
#   $r.Errors     what it wrote to stderr, or why it could not be started
#   -Show         also writes each stdout line to the console as it comes (a long install)
#
# Load it with:  . (Join-Path $Root "scripts\eli_native.ps1")
function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [string[]]$Arguments = @(),
        [switch]$Show
    )
    $ErrorActionPreference = "Continue"
    $out = New-Object System.Collections.Generic.List[string]
    $err = New-Object System.Collections.Generic.List[string]
    $code = $null
    try {
        & $Exe @Arguments 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) {
                $err.Add("$_")
            } else {
                $out.Add("$_")
                if ($Show) { Write-Host "$_" }
            }
        }
        $code = $LASTEXITCODE
    } catch {
        $err.Add("$_")
    }
    return [pscustomobject]@{ ExitCode = $code; Output = $out.ToArray(); Errors = $err.ToArray() }
}
