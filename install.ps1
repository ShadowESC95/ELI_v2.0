# ELI MKXI — Windows PowerShell installer
# Run: powershell -ExecutionPolicy Bypass -File install.ps1 [-CpuOnly] [-CudaVersion cu121]

param(
    [switch]$CpuOnly,
    [string]$CudaVersion = "cu121"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $ScriptDir ".venv"
$RequirementCandidates = @(
    (Join-Path $ScriptDir "requirements-windows.txt"),
    (Join-Path $ScriptDir "requirements.txt")
)
$RequirementsFile = $RequirementCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

$WheelhouseCandidates = @(
    (Join-Path $ScriptDir "wheelhouse"),
    (Join-Path $ScriptDir "dist\wheelhouse")
)
$Wheelhouse = $WheelhouseCandidates |
    Where-Object { (Test-Path $_) -and (Get-ChildItem $_ -Filter "*.whl" -ErrorAction SilentlyContinue | Select-Object -First 1) } |
    Select-Object -First 1
$PipFindLinksArgs = @("--prefer-binary")
if ($Wheelhouse) {
    $PipFindLinksArgs = @("--find-links", $Wheelhouse, "--prefer-binary")
}

Write-Host ""
Write-Host "==============================" -ForegroundColor Cyan
Write-Host "  ELI MKXI Installer (Windows)" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan
Write-Host ""

# Check Python
try {
    $pyVer = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    if ([Version]$pyVer -lt [Version]"3.11") {
        throw "Python 3.11+ required, found $pyVer"
    }
    Write-Host "[OK] Python $pyVer" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python 3.11+ not found." -ForegroundColor Red
    Write-Host "        Download from https://python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

# Create venv
if (Test-Path "$Venv\Scripts\activate.ps1") {
    Write-Host "[OK] Virtual environment already exists." -ForegroundColor Green
} else {
    Write-Host "[..] Creating virtual environment..."
    & python -m venv $Venv
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create virtual environment at $Venv"
    }
}

$Pip = "$Venv\Scripts\pip.exe"
$PythonVenv = "$Venv\Scripts\python.exe"

function Invoke-Pip {
    param([string[]]$Arguments)

    & $Pip @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "pip failed: $($Arguments -join ' ')"
    }
}

if (-not $RequirementsFile) {
    throw "Could not find requirements-windows.txt or requirements.txt in $ScriptDir"
}
Write-Host "[OK] Requirements: $RequirementsFile" -ForegroundColor Green
if ($Wheelhouse) {
    Write-Host "[OK] Using bundled wheelhouse: $Wheelhouse" -ForegroundColor Green
}

Write-Host "[..] Upgrading pip..."
Invoke-Pip @("install", "--quiet", "--upgrade", "pip", "setuptools", "wheel")

# PyTorch
if ($CpuOnly) {
    Write-Host "[..] Installing PyTorch (CPU)..."
    Invoke-Pip (@("install") + $PipFindLinksArgs + @("torch", "--index-url", "https://download.pytorch.org/whl/cpu", "--quiet"))
} else {
    Write-Host "[..] Installing PyTorch (CUDA $CudaVersion)..."
    Invoke-Pip @("install", "torch", "--index-url", "https://download.pytorch.org/whl/$CudaVersion", "--prefer-binary", "--quiet")
}

# llama-cpp-python
if ($CpuOnly) {
    Write-Host "[..] Installing llama-cpp-python (CPU)..."
    Invoke-Pip (@("install") + $PipFindLinksArgs + @("llama-cpp-python", "--quiet"))
} else {
    Write-Host "[..] Installing llama-cpp-python (CUDA $CudaVersion)..."
    Invoke-Pip @("install", "llama-cpp-python", "--prefer-binary", "--extra-index-url", "https://abetlen.github.io/llama-cpp-python/whl/$CudaVersion", "--quiet")
}

# ELI MKXI wheel
Write-Host "[..] Installing ELI MKXI..."
$Wheel = Get-ChildItem (Join-Path $ScriptDir "dist") -Filter "eli_mkxi-*.whl" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($Wheel) {
    Invoke-Pip (@("install") + $PipFindLinksArgs + @("$($Wheel.FullName)[full]", "--quiet"))
} else {
    Invoke-Pip (@("install") + $PipFindLinksArgs + @("-e", "$ScriptDir[full]", "--quiet"))
}

# Remaining deps
Write-Host "[..] Installing remaining dependencies..."
Invoke-Pip (@("install") + $PipFindLinksArgs + @("-r", $RequirementsFile, "--quiet"))

Write-Host ""
Write-Host "==============================" -ForegroundColor Green
Write-Host "  Installation complete!" -ForegroundColor Green
Write-Host "==============================" -ForegroundColor Green
Write-Host ""
Write-Host "Launch ELI:" -ForegroundColor Cyan
Write-Host "  .\eli.bat" -ForegroundColor White
Write-Host ""
try {
    $ModelsDir = & $PythonVenv -c "from eli.core.paths import models_dir; print(models_dir())" 2>$null
    if ($ModelsDir) {
        Write-Host "Models location: $ModelsDir" -ForegroundColor Cyan
    }
} catch {
    Write-Host "Models location: use the app data models directory or set ELI_MODELS_DIR" -ForegroundColor Cyan
}
