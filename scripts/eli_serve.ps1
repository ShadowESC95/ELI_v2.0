# ELI API / web-app server launcher (Windows). Mirrors scripts/eli_serve.sh.
#   Safe by default: binds 127.0.0.1 (this machine only), tokenless. Inference runs HERE;
#   nothing reaches the cloud.
#   -Lan         expose to your local network for a phone/tablet browser (binds 0.0.0.0
#                AND mints an access token; prints the exact URL to open on the device).
#   -Port <n>    listen port (default 8081)
#   -Token <s>   use a specific token instead of a generated one
param(
    [switch]$Lan,
    [int]$Port = 8081,
    [string]$Token = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { Write-Host "[eli-serve] .venv not found - run install.ps1 first."; exit 1 }

if ($Lan) {
    $env:ELI_API_HOST = "0.0.0.0"
    if (-not $Token) { $Token = & $Py -c "import secrets; print(secrets.token_urlsafe(16))" }
    $env:ELI_API_TOKEN = $Token
    $ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
           Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.*' } |
           Select-Object -First 1).IPAddress
    if (-not $ip) { $ip = "<this-host-ip>" }
    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host " ELI server - LAN mode (token-protected, still 100% local)" -ForegroundColor Cyan
    Write-Host "   On a phone/tablet on the SAME network, open:"
    Write-Host ""
    Write-Host "     http://${ip}:$Port/#token=$Token" -ForegroundColor White
    Write-Host ""
    Write-Host "   The page stores the token; afterwards just http://${ip}:$Port/ works."
    Write-Host "   Inference runs on THIS machine - nothing leaves it to any cloud."
    Write-Host "======================================================================" -ForegroundColor Cyan
} else {
    $env:ELI_API_HOST = "127.0.0.1"
    Write-Host "[eli-serve] local-only at http://127.0.0.1:$Port/   (use -Lan for phone access)"
}
$env:ELI_API_PORT = "$Port"
Set-Location $Root
& $Py -m api.server
