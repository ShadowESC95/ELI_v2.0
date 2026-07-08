# ELI API / web-app server launcher (Windows). Mirrors scripts/eli_serve.sh.
#   Safe by default: binds 127.0.0.1 (this machine only), tokenless. Inference runs HERE;
#   nothing reaches the cloud.
#   -Lan         expose to your local network for a phone/tablet browser (binds 0.0.0.0
#                AND mints an access token; prints the exact URL to open on the device).
#   -Https       also serve HTTPS on port 8443 (phone microphone over LAN).
#   -Port <n>    listen port (default 8081)
#   -Token <s>   use a specific token instead of a generated one
param(
    [switch]$Lan,
    [switch]$Https,
    [int]$Port = 8081,
    [string]$Token = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { Write-Host "[eli-serve] .venv not found - run install.ps1 first."; exit 1 }

$env:ELI_PROJECT_ROOT = $Root
$env:ELI_DATA_DIR = if ($env:ELI_DATA_DIR) { $env:ELI_DATA_DIR } else { Join-Path $Root "artifacts" }
$env:ELI_CONFIG_DIR = if ($env:ELI_CONFIG_DIR) { $env:ELI_CONFIG_DIR } else { Join-Path $Root "config" }
$env:ELI_MODELS_DIR = if ($env:ELI_MODELS_DIR) { $env:ELI_MODELS_DIR } else { Join-Path $Root "models" }
$env:PYTHONPATH = $Root

$serverArgs = @()
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
    Write-Host "     http://${ip}:$Port/" -ForegroundColor White
    Write-Host ""
    if ($Https) {
        Write-Host "   Phone microphone (voice) - HTTPS:"
        Write-Host "     https://${ip}:8443/" -ForegroundColor White
    } else {
        Write-Host "   Tip: add -Https to enable the phone microphone (voice)."
    }
    Write-Host "   Token URL is printed below once the server starts."
    Write-Host "======================================================================" -ForegroundColor Cyan
    $serverArgs += "--lan"
} else {
    $env:ELI_API_HOST = "127.0.0.1"
    Write-Host "[eli-serve] local-only at http://127.0.0.1:$Port/   (use -Lan for phone access)"
}
if ($Https) {
    $env:ELI_API_HTTPS = "1"
    $serverArgs += "--https"
}
if ($Token) { $serverArgs += @("--token", $Token) }
$serverArgs += @("--port", "$Port")
$env:ELI_API_PORT = "$Port"
Set-Location $Root

$needVoice = $false
& $Py -c "from eli.perception.local_whisper_stt import whisper_cache_ready; import sys; sys.exit(0 if whisper_cache_ready() else 1)" 2>$null
if ($LASTEXITCODE -ne 0) { $needVoice = $true }
& $Py -c "from eli.runtime.voice_assets import piper_voice_ready; import sys; sys.exit(0 if piper_voice_ready() else 1)" 2>$null
if ($LASTEXITCODE -ne 0) { $needVoice = $true }
if ($needVoice) {
    Write-Host "[eli-serve] Voice models not cached - fetching once..."
    & $Py -m eli.runtime.voice_assets
}

& $Py -m api.server @serverArgs
