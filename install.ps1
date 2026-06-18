# ELI MKXI — Windows PowerShell installer
# Run: powershell -ExecutionPolicy Bypass -File install.ps1 [-CpuOnly] [-Latest] [-InstallCuda] [-CudaVersion cu121]

param(
    [switch]$CpuOnly,
    [switch]$Gpu,           # force the GPU build even if no NVIDIA GPU is detected
    [switch]$Latest,        # use requirements.txt ranges instead of the frozen lock
    [switch]$InstallCuda,   # best-effort install the CUDA toolkit via winget if missing
    [switch]$Yes,           # non-interactive: accept the plan + use detected defaults
    [switch]$AutoModel,     # download a model (sized to VRAM) after install
    [switch]$NoModel,       # never download a model
    [string]$Model = "",    # download a specific model key after install
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
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  ELI MKXI - Installer (Windows)" -ForegroundColor Cyan
Write-Host "  100% local - private - offline-by-default" -ForegroundColor DarkGray
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# Check Python
try {
    $pyVer = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    if ([Version]$pyVer -lt [Version]"3.10") {
        throw "Python 3.10+ required, found $pyVer"
    }
} catch {
    Write-Host "[ERROR] Python 3.10+ not found." -ForegroundColor Red
    Write-Host "        Download from https://python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

# ── System report — full info before anything runs ──
Write-Host "--- Your system ---" -ForegroundColor Magenta
Write-Host "[OK] Python      $pyVer" -ForegroundColor Green
Write-Host "[OK] Platform    Windows ($([System.Environment]::OSVersion.Version))" -ForegroundColor Green
$cpuCores = $env:NUMBER_OF_PROCESSORS
try { $ramGb = [math]::Round((Get-CimInstance Win32_ComputerSystem -ErrorAction Stop).TotalPhysicalMemory / 1GB) } catch { $ramGb = "?" }
Write-Host "[OK] CPU         $cpuCores cores      RAM $ramGb GB" -ForegroundColor Green
try {
    $drive = Get-PSDrive -Name ($ScriptDir.Substring(0,1)) -ErrorAction Stop
    $freeGb = [math]::Round($drive.Free / 1GB)
    Write-Host "[OK] Disk free   $freeGb GB   (a model is ~2-5 GB)" -ForegroundColor Green
} catch {}
$HasNvidia = $false
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $gpuNames = @(& nvidia-smi --query-gpu=name --format=csv,noheader 2>$null | Where-Object { $_ })
    if ($gpuNames.Count -ge 1) {
        $vramTot = (& nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>$null | Measure-Object -Sum).Sum
        if ($gpuNames.Count -gt 1) {
            Write-Host "[OK] GPU         $($gpuNames.Count)x $($gpuNames[0])  ($vramTot MiB total VRAM)" -ForegroundColor Green
        } else {
            Write-Host "[OK] GPU         $($gpuNames[0])  ($vramTot MiB)" -ForegroundColor Green
        }
        $HasNvidia = $true
    }
}
if (-not $HasNvidia) { Write-Host "[WARN] GPU       none detected - ELI will run on CPU (slower)" -ForegroundColor Yellow }

# Default the build to the hardware unless forced.
if ((-not $CpuOnly) -and (-not $Gpu) -and (-not $HasNvidia)) { $CpuOnly = $true }
$BuildLabel = if ($CpuOnly) { "CPU-only" } else { "GPU (CUDA $CudaVersion)" }

# ── Plan ──
Write-Host ""
Write-Host "--- Plan ---" -ForegroundColor Magenta
Write-Host "  - llama-cpp build : $BuildLabel"
Write-Host ("  - dependencies    : " + $(if ($Latest) { "latest ranges" } else { "frozen lock (reproducible)" }))
Write-Host ("  - a model         : " + $(if ($NoModel) { "skip (add one later)" } else { "offered after install" }))
Write-Host "  - data            : offline-by-default, fresh local databases"
if (-not $Yes) {
    $ans = Read-Host "  Proceed? [Y/n]"
    if ($ans -match '^[Nn]') { Write-Host "Aborted - nothing changed."; exit 0 }
    if ((-not $NoModel) -and (-not $AutoModel) -and (-not $Model)) {
        $m = Read-Host "  Download a model now, sized to your hardware? [Y/n]"
        if ($m -match '^[Nn]') { $NoModel = $true } else { $AutoModel = $true }
    }
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

# ── Optional system tools (best-effort via winget): ffmpeg = media/whisper, tesseract = OCR ──
# Non-fatal. Windows uses native APIs for volume/clipboard/notifications, so only these help.
if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "[..] Installing optional system tools (ffmpeg, tesseract) via winget..."
    foreach ($id in @("Gyan.FFmpeg", "UB-Mannheim.TesseractOCR")) {
        winget install --id $id --silent --accept-package-agreements --accept-source-agreements 2>$null
    }
    Write-Host "[OK] Optional system tools step done (skips any already present)." -ForegroundColor Green
} else {
    Write-Host "[..] winget not found — optional: install FFmpeg + Tesseract OCR for media/OCR features." -ForegroundColor DarkGray
}

# ── Optional model download — the one online step ──
$ModelStatus = "none yet"
$existingModel = Get-ChildItem (Join-Path $ScriptDir "models") -Filter "*.gguf" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existingModel) {
    $ModelStatus = "already present"
} elseif ((-not $NoModel) -and ($AutoModel -or $Model)) {
    Write-Host "[..] Downloading a model (sized to your VRAM) - the one online step..."
    $modelArg = if ($Model) { $Model } else { "--auto" }
    & $PythonVenv -m eli.core.model_download $modelArg
    if ($LASTEXITCODE -eq 0) { $ModelStatus = "downloaded" } else { $ModelStatus = "download failed (fetch later)" }
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host "  ELI MKXI - installation complete" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
Write-Host ""
Write-Host "--- Summary ---" -ForegroundColor Magenta
Write-Host "[OK] Build       llama-cpp $BuildLabel" -ForegroundColor Green
Write-Host "[OK] Model       $ModelStatus" -ForegroundColor Green
Write-Host "[OK] Data        fresh local databases, offline-by-default" -ForegroundColor Green
Write-Host ""
Write-Host "--- Launch ---" -ForegroundColor Magenta
Write-Host "  .\eli.bat                                  # desktop app (GUI)" -ForegroundColor White
Write-Host "  .\scripts\eli_serve.ps1 -Lan               # web app for phone / tablet" -ForegroundColor White
Write-Host "  powershell -File scripts\install_desktop_apps.ps1   # add Start Menu shortcuts" -ForegroundColor White
Write-Host ""
if (($ModelStatus -eq "none yet") -or ($ModelStatus -like "download failed*")) {
    Write-Host "  No model yet - the first-run wizard offers a download, or run:" -ForegroundColor DarkGray
    Write-Host "    .venv\Scripts\python -m eli.core.model_download --auto" -ForegroundColor White
    Write-Host ""
}
Write-Host "ELI stays offline by default; model downloads are a deliberate one-time action." -ForegroundColor DarkGray
