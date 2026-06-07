# ELI MKXI — Windows PowerShell installer
# Run: powershell -ExecutionPolicy Bypass -File install.ps1 [-CpuOnly] [-Latest] [-InstallCuda] [-CudaVersion cu121]

param(
    [switch]$CpuOnly,
    [switch]$Latest,        # use requirements.txt ranges instead of the frozen lock
    [switch]$InstallCuda,   # best-effort install the CUDA toolkit via winget if missing
    [string]$CudaVersion = "cu121"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $ScriptDir ".venv"
# Frozen lock by default (reproducible); -Latest uses the Windows/range profile.
$RequirementCandidates = if ($Latest) {
    @( (Join-Path $ScriptDir "requirements-windows.txt"), (Join-Path $ScriptDir "requirements.txt") )
} else {
    @( (Join-Path $ScriptDir "requirements.lock.txt"),
       (Join-Path $ScriptDir "requirements-windows.txt"),
       (Join-Path $ScriptDir "requirements.txt") )
}
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

# Verify llama-cpp GPU offload actually compiled in (catch a silent CPU-only wheel).
if (-not $CpuOnly) {
    & $PythonVenv -c "import llama_cpp,sys; sys.exit(0 if llama_cpp.llama_supports_gpu_offload() else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] llama-cpp-python has CUDA GPU offload." -ForegroundColor Green
    } elseif ($InstallCuda) {
        Write-Host "[WARN] prebuilt llama-cpp is CPU-only — installing CUDA toolkit (winget) + rebuilding..." -ForegroundColor Yellow
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            winget install --id Nvidia.CUDA --silent --accept-package-agreements --accept-source-agreements 2>$null
        } else {
            Write-Host "        winget not found — install the CUDA Toolkit from https://developer.nvidia.com/cuda-downloads" -ForegroundColor Yellow
        }
        $env:CMAKE_ARGS = "-DGGML_CUDA=on"
        & $Pip install --force-reinstall --no-cache-dir llama-cpp-python --quiet
        & $PythonVenv -c "import llama_cpp,sys; sys.exit(0 if llama_cpp.llama_supports_gpu_offload() else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { Write-Host "[OK] llama-cpp-python rebuilt with CUDA." -ForegroundColor Green }
        else { Write-Host "[WARN] still CPU-only — ELI will run on CPU." -ForegroundColor Yellow }
    } else {
        Write-Host "[WARN] llama-cpp-python is CPU-ONLY — ELI will be slow. Re-run with -InstallCuda to fix." -ForegroundColor Yellow
    }
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
Write-Host "[..] Installing dependencies from $(Split-Path $RequirementsFile -Leaf)..."
Invoke-Pip (@("install") + $PipFindLinksArgs + @("-r", $RequirementsFile, "--quiet"))

# Seed a clean offline config (never overwrite) + init data dirs/databases.
$Settings = Join-Path $ScriptDir "config\settings.json"
$Template = Join-Path $ScriptDir "config\templates\settings.template.json"
if ((-not (Test-Path $Settings)) -and (Test-Path $Template)) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ScriptDir "config") | Out-Null
    Copy-Item $Template $Settings
    Write-Host "[OK] Seeded clean config: config\settings.json" -ForegroundColor Green
}
New-Item -ItemType Directory -Force -Path (Join-Path $ScriptDir "models") | Out-Null
Write-Host "[..] Initialising data directories and databases..."
& $PythonVenv -c "from eli.core.paths import get_paths; get_paths(); import eli.memory as M; (M.get_memory() if hasattr(M,'get_memory') else None)" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Host "[OK] Data dirs + databases ready." -ForegroundColor Green }

Write-Host ""
Write-Host "==============================" -ForegroundColor Green
Write-Host "  Installation complete!" -ForegroundColor Green
Write-Host "==============================" -ForegroundColor Green
Write-Host ""
Write-Host "Launch ELI:" -ForegroundColor Cyan
Write-Host "  .\eli.bat" -ForegroundColor White
Write-Host ""
Write-Host "Download a model (first run also offers this in the wizard):" -ForegroundColor Cyan
Write-Host "  .venv\Scripts\python -m eli.core.model_download --auto" -ForegroundColor White
Write-Host ""
try {
    $ModelsDir = & $PythonVenv -c "from eli.core.paths import models_dir; print(models_dir())" 2>$null
    if ($ModelsDir) {
        Write-Host "Models location: $ModelsDir" -ForegroundColor Cyan
    }
} catch {
    Write-Host "Models location: use the app data models directory or set ELI_MODELS_DIR" -ForegroundColor Cyan
}
