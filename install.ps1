# ELI v2.0 -- Windows PowerShell installer
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

function Eli-Progress {
    param([string]$Phase, [int]$Pct, [string]$Msg)
    Write-Host "[ELI-PROGRESS] phase=$Phase pct=$Pct msg=$Msg"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
# Invoke-Native: every check of a program, and every program whose output is hidden, goes through
# it. Under "Stop", Windows PowerShell 5.1 ends the script on the first line a program writes to a
# redirected stderr; the helper relaxes that for its own call only.
. (Join-Path $ScriptDir "scripts\eli_native.ps1")
$Venv = Join-Path $ScriptDir ".venv"
$env:ELI_PROJECT_ROOT = $ScriptDir
if (-not $env:ELI_DATA_DIR) { $env:ELI_DATA_DIR = Join-Path $ScriptDir "artifacts" }
if (-not $env:ELI_CONFIG_DIR) { $env:ELI_CONFIG_DIR = Join-Path $ScriptDir "config" }
if (-not $env:ELI_MODELS_DIR) { $env:ELI_MODELS_DIR = Join-Path $ScriptDir "models" }
if (-not $env:ELI_CACHE_DIR) { $env:ELI_CACHE_DIR = Join-Path $ScriptDir "cache" }
if ($env:PYTHONPATH) { $env:PYTHONPATH = "$ScriptDir;$env:PYTHONPATH" } else { $env:PYTHONPATH = $ScriptDir }
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
Write-Host "  ELI v2.0 - Installer (Windows)" -ForegroundColor Cyan
Write-Host "  100% local - private - offline-by-default" -ForegroundColor DarkGray
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# Check Python: the installed one the most of ELI's packages come ready-made for (scripts\eli_env.py
# pick). Its stderr isn't redirected: Windows PowerShell turns redirected stderr into errors.
$Python = "python"
$BootPython = $null
if (Get-Command python -ErrorAction SilentlyContinue) { $BootPython = "python" }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $BootPython = "py" }
$EnvHelper = Join-Path $ScriptDir "scripts\eli_env.py"
if ($BootPython -and (Test-Path $EnvHelper)) {
    try {
        $Picked = & $BootPython $EnvHelper pick
        if ($LASTEXITCODE -eq 0 -and $Picked) { $Python = ("$Picked").Trim() }
    } catch { $Python = "python" }
}
# The floor is what pyproject.toml declares (eli_env.py versions, oldest first).
$Floor = $null
try {
    $pyVer = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    $Floor = @(& $Python $EnvHelper versions)[0]
    if (-not $Floor -or [Version]$pyVer -lt [Version]$Floor) {
        throw "Python $Floor or newer required, found $pyVer"
    }
} catch {
    Write-Host "[ERROR] Python $(if ($Floor) { "$Floor or newer" } else { '3' }) not found." -ForegroundColor Red
    Write-Host "        Download from https://python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

# -- System report -- full info before anything runs --
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
    # A driver that cannot answer prints why on stdout and exits non-zero: only a run that
    # succeeded names GPUs (as in install.sh and eli.setup.hardware_policy).
    $Smi = Invoke-Native nvidia-smi @("--query-gpu=name", "--format=csv,noheader")
    $gpuNames = @(if ($Smi.ExitCode -eq 0) { $Smi.Output | Where-Object { $_.Trim() } })
    if ($gpuNames.Count -ge 1) {
        $vramTot = ((Invoke-Native nvidia-smi @("--query-gpu=memory.total", "--format=csv,noheader,nounits")).Output |
            Where-Object { $_ -match '^\s*\d+\s*$' } | Measure-Object -Sum).Sum
        if ($gpuNames.Count -gt 1) {
            Write-Host "[OK] GPU         $($gpuNames.Count)x $($gpuNames[0])  ($vramTot MiB total VRAM)" -ForegroundColor Green
        } else {
            Write-Host "[OK] GPU         $($gpuNames[0])  ($vramTot MiB)" -ForegroundColor Green
        }
        $HasNvidia = $true
    }
}
if (-not $HasNvidia) {
    # nvidia-smi was the ONLY detector here, so an AMD or Intel Arc machine was
    # told it had no GPU at all and silently dropped to a CPU-only build with
    # no explanation. Enumerate every adapter and say what is actually present.
    $OtherGpus = @()
    try {
        $OtherGpus = @(Get-CimInstance Win32_VideoController -ErrorAction Stop |
            Where-Object { $_.Name -and $_.Name -notmatch '(?i)nvidia' -and
                           $_.Name -notmatch '(?i)microsoft basic display' } |
            ForEach-Object { $_.Name.Trim() })
    } catch { $OtherGpus = @() }

    if ($OtherGpus.Count -ge 1) {
        Write-Host "[OK] GPU         $($OtherGpus[0])" -ForegroundColor Green
        $isQualcomm = $OtherGpus[0] -match '(?i)qualcomm|adreno|snapdragon'
        $vendor = if ($OtherGpus[0] -match '(?i)amd|radeon') { "AMD" }
                  elseif ($OtherGpus[0] -match '(?i)intel|arc') { "Intel" }
                  elseif ($isQualcomm) { "Qualcomm Snapdragon" }
                  else { "this vendor" }
        if ($isQualcomm) {
            Write-Host "            Snapdragon unified memory - layer fit uses shared RAM budget." -ForegroundColor DarkGray
            Write-Host "            Vulkan offload is experimental on Adreno; keep batch_size <= 32." -ForegroundColor DarkGray
        }
        Write-Host "[WARN] GPU       $vendor GPU found, but no prebuilt GPU-accelerated" -ForegroundColor Yellow
        Write-Host "                 llama-cpp-python wheel is published for it on Windows." -ForegroundColor Yellow
        Write-Host "                 ELI will use the CPU build (it still runs, just slower)." -ForegroundColor Yellow
        Write-Host "                 A Vulkan build can be compiled manually - see docs." -ForegroundColor Yellow
    } else {
        Write-Host "[WARN] GPU       none detected - ELI will run on CPU (slower)" -ForegroundColor Yellow
    }
}

# Default the build to the hardware unless forced.
if ((-not $CpuOnly) -and (-not $Gpu) -and (-not $HasNvidia)) { $CpuOnly = $true }
$BuildLabel = if ($CpuOnly) { "CPU-only" } else { "GPU (CUDA $CudaVersion)" }

# Low-RAM advisory. install.sh forces CPU here because a Vulkan SOURCE build OOMs
# on <=8 GB laptops; Windows takes prebuilt wheels so the build itself is safe, but
# the machine still cannot hold a large model plus a CUDA context. Say so up front
# rather than letting the first model load discover it.
if (($ramGb -is [int]) -and ($ramGb -le 8)) {
    Write-Host "[WARN] RAM         $ramGb GB - choose a small model (3B-class or Q4) and keep" -ForegroundColor Yellow
    Write-Host "                   the context modest; ELI sizes itself to fit but headroom is tight." -ForegroundColor Yellow
}

# -- Plan --
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
        $m = Read-Host "  Choose model(s) to download now? [Y/n]"
        # --choose opens a multi-select menu (pick any number, or auto/all/none). Declining
        # skips only the chat model, as in install.sh: the small embedder memory and recall
        # need is still fetched below. -NoModel stays the one way to skip both.
        $ChooseModel = -not ($m -match '^[Nn]')
    }
}

# Create venv. One whose Python has been removed or replaced exists but cannot start: mend it
# in place when an interpreter of its version is still installed, else rebuild it.
$VenvOk = $false
if (Test-Path "$Venv\Scripts\activate.ps1") {
    try {
        & $Python $EnvHelper status $ScriptDir | Out-Null
        if ($LASTEXITCODE -ne 0) { & $Python $EnvHelper repair $ScriptDir | Out-Null }
        $VenvOk = ($LASTEXITCODE -eq 0)
    } catch { $VenvOk = $true }
    if (-not $VenvOk) {
        Write-Host "[..] Existing .venv no longer matches this system - rebuilding..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force $Venv
    }
}
if ($VenvOk) {
    Write-Host "[OK] Virtual environment already exists." -ForegroundColor Green
} else {
    Write-Host "[..] Creating virtual environment..."
    & $Python -m venv $Venv
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create virtual environment at $Venv"
    }
}

# pip is always run as "python -m pip". pip.exe cannot replace itself: "Upgrading pip" ended
# the installer on every Windows Python that came with a pip older than the newest.
$PythonVenv = "$Venv\Scripts\python.exe"

function Invoke-Pip {
    param([string[]]$Arguments)

    & $PythonVenv -m pip @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "pip failed: $($Arguments -join ' ')"
    }
}

# Whether a Python check in the venv passes, by its exit code; what it prints is not shown.
function Test-VenvPython {
    param([string]$Code)
    return ((Invoke-Native $PythonVenv @("-c", $Code)).ExitCode -eq 0)
}

if (-not $RequirementsFile) {
    throw "Could not find requirements-windows.txt or requirements.txt in $ScriptDir"
}
Write-Host "[OK] Requirements: $RequirementsFile" -ForegroundColor Green
if ($Wheelhouse) {
    Write-Host "[OK] Using bundled wheelhouse: $Wheelhouse" -ForegroundColor Green
}

Write-Host "[..] Upgrading pip..."
Invoke-Pip @("install", "--quiet", "--upgrade", "pip", "wheel")
Invoke-Pip @("install", "--quiet", "setuptools>=68,<82")

# PyTorch
Eli-Progress -Phase torch -Pct 20 -Msg "Installing PyTorch"
if ($CpuOnly) {
    Write-Host "[..] Installing PyTorch (CPU)..."
    Invoke-Pip (@("install") + $PipFindLinksArgs + @("torch", "--index-url", "https://download.pytorch.org/whl/cpu", "--quiet"))
} else {
    # The newest CUDA build for this Python and driver (eli_env.py torch-index) unless -CudaVersion
    # is given. Newer builds drop older cards, so one that won't run here gives way to the oldest.
    if ($PSBoundParameters.ContainsKey('CudaVersion')) {
        $TorchIndexes = @("https://download.pytorch.org/whl/$CudaVersion")
    } else {
        $TorchIndexes = @(& $PythonVenv $EnvHelper torch-index cuda | Where-Object { $_ })
    }
    $TorchTry = @(@($TorchIndexes | Select-Object -First 1) + @($TorchIndexes | Select-Object -Last 1) | Select-Object -Unique)
    $TorchOnGpu = $false
    foreach ($TorchIndex in $TorchTry) {
        Write-Host "[..] Installing PyTorch (CUDA build $($TorchIndex.Split('/')[-1]))..."
        & $PythonVenv -m pip install torch --index-url $TorchIndex --only-binary=:all: --quiet
        if ($LASTEXITCODE -eq 0) {
            $TorchOnGpu = Test-VenvPython "import sys, torch; x = torch.ones(1, device='cuda'); sys.exit(0 if (x + 1).item() == 2 else 1)"
        }
        if (-not $TorchOnGpu) { Invoke-Native $PythonVenv @("-m", "pip", "uninstall", "-y", "torch") | Out-Null }
        if ($TorchOnGpu) { Write-Host "[OK] PyTorch $($TorchIndex.Split('/')[-1]) runs on the GPU." -ForegroundColor Green; break }
    }
    if (-not $TorchOnGpu) {
        Write-Host "[WARN] No PyTorch CUDA build installed and ran on this GPU with Python $pyVer - using the CPU build." -ForegroundColor Yellow
        Write-Host "       What uses PyTorch runs on the CPU; the language model is not affected." -ForegroundColor Yellow
        Invoke-Pip (@("install") + $PipFindLinksArgs + @("torch", "--index-url", "https://download.pytorch.org/whl/cpu", "--only-binary=:all:", "--quiet"))
    }
}

# llama-cpp-python. PyPI publishes it as source only, so a ready-made build comes from the CUDA
# wheel index (NVIDIA) or a bundled wheelhouse. Without one it is built here, which takes several
# minutes and needs the Microsoft C++ Build Tools. A build that fails is said plainly and the install
# goes on: ELI starts, and runs a local model once the engine is in.
Eli-Progress -Phase llama -Pct 35 -Msg "Installing inference engine"
$LlamaReq = "llama-cpp-python>=0.3.35"
$LlamaBuilt = $false
# AVX2 floor, not cmake's native tuning (the -InstallCuda rebuild below says why).
$LlamaCpuFlags = "-DGGML_NATIVE=OFF -DCMAKE_C_FLAGS=/arch:AVX2 -DCMAKE_CXX_FLAGS=/arch:AVX2"

# Builds the engine here from its source with these CMake flags, and sets $LlamaBuilt.
function Build-LlamaHere {
    param([string]$Reason, [string]$CmakeArgs, [string]$IfFailed, [string[]]$Extra = @())
    $ErrorActionPreference = "Continue"
    Write-Host "[..] $Reason" -ForegroundColor Yellow
    Write-Host "     Building llama-cpp-python here: several minutes, and it needs the Microsoft C++ Build Tools." -ForegroundColor Yellow
    $env:CMAKE_ARGS = $CmakeArgs
    & $PythonVenv -m pip install @Extra --no-cache-dir --no-binary llama-cpp-python $LlamaReq --quiet
    $script:LlamaBuilt = ($LASTEXITCODE -eq 0)
    Remove-Item Env:CMAKE_ARGS -ErrorAction SilentlyContinue
    if (-not $script:LlamaBuilt) {
        Write-Host "[WARN] The build failed: $IfFailed" -ForegroundColor Yellow
        Write-Host "       Without the C++ build tools it cannot build. Add them, then run this installer again:" -ForegroundColor Yellow
        Write-Host '         winget install Microsoft.VisualStudio.2022.BuildTools --override "--passive --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"' -ForegroundColor Yellow
        Write-Host "       Or install ELI-Setup-<version>.exe from the Releases page, which brings its own engine." -ForegroundColor Yellow
    }
}

$NoEngineYet = "ELI starts, but cannot run a local model until the engine is in."
if ($CpuOnly) {
    Write-Host "[..] Installing llama-cpp-python (CPU)..."
    & $PythonVenv -m pip install @PipFindLinksArgs $LlamaReq "--only-binary=:all:" --quiet
    if ($LASTEXITCODE -ne 0) {
        Build-LlamaHere -Reason "No ready-made llama-cpp-python 0.3.35 or newer for Python $pyVer here (PyPI has its source only)." -CmakeArgs $LlamaCpuFlags -IfFailed $NoEngineYet
    }
} else {
    Write-Host "[..] Installing llama-cpp-python (CUDA $CudaVersion)..."
    # --only-binary=:all: is the important part. With --prefer-binary, pip
    # falls back to building from source when the CUDA index has no wheel for
    # this Python version, unannounced; that needs the MSVC toolchain, and its
    # failure aborted the whole installer at the last step, right after "GPU
    # accelerator". The source build below is said first, and the install goes
    # on when it fails.
    $llamaCudaOk = $false
    try {
        # The CUDA wheel index is stale: it stops at 0.3.19 for cp312, and
        # anything below 0.3.30 cannot read hybrid attention+SSM GGUFs
        # (qwen35, nemotron-h) - they fail on a missing ssm_conv1d tensor.
        # Require a version that can, rather than silently taking an old wheel.
        Invoke-Pip @("install", "llama-cpp-python>=0.3.35", "--only-binary=:all:", "--extra-index-url", "https://abetlen.github.io/llama-cpp-python/whl/$CudaVersion", "--quiet")
        $llamaCudaOk = $true
    } catch {
        Write-Host "[WARN] No prebuilt CUDA $CudaVersion wheel for llama-cpp-python on Python $pyVer." -ForegroundColor Yellow
        Write-Host "       (The CUDA wheel index tops out at 0.3.19 for some Python versions;" -ForegroundColor Yellow
        Write-Host "        ELI needs >=0.3.35 to read current GGUF architectures and plan loads.)" -ForegroundColor Yellow
        Write-Host "       For GPU offload:" -ForegroundColor Yellow
        Write-Host "         - re-run with -CudaVersion cu124 (or another published version)" -ForegroundColor Yellow
        Write-Host "         - re-run with -InstallCuda to build with CUDA locally" -ForegroundColor Yellow
    }
    if (-not $llamaCudaOk) {
        # PyPI has no llama-cpp-python wheel to fall back to: the CPU engine is built here.
        Build-LlamaHere -Reason "Building the CPU engine so the install completes." -CmakeArgs $LlamaCpuFlags -IfFailed $NoEngineYet
        # Keep the rest of the run honest: the offload verify below and the summary must not
        # claim a GPU build that was not installed. With -InstallCuda that step rebuilds it with CUDA.
        if (-not $InstallCuda) {
            $CpuOnly = $true
            $BuildLabel = "CPU-only (CUDA wheel unavailable)"
        }
    }
}

# Verify the installed runtime actually STARTS on this CPU.
#
# Parity with install.sh's "measure init, not import" policy. Prebuilt wheels ship a
# libggml-cpu tuned for newer chips (AVX-VNNI and friends): `import llama_cpp`
# succeeds and llama_backend_init() then dies with STATUS_ILLEGAL_INSTRUCTION
# (0xC000001D) on an older Intel part. Windows had no equivalent check, so the
# install reported success and the app crashed on first launch with nothing to
# explain it. Catch it here, while a fallback is still cheap.
$StartsHere = "from llama_cpp import llama_cpp as _lc; _lc.llama_backend_init()"
$BuildWarn = $false
if (-not (Test-VenvPython "import llama_cpp")) {
    Write-Host "[WARN] llama-cpp-python is not installed. $NoEngineYet" -ForegroundColor Yellow
    $CpuOnly = $true
    $BuildWarn = $true
    $BuildLabel = "NOT installed - no local model until it is (see above)"
} elseif (Test-VenvPython $StartsHere) {
    Write-Host "[OK] llama-cpp runtime starts on this CPU." -ForegroundColor Green
} else {
    Write-Host "[WARN] llama-cpp failed to initialise on this CPU (exit $LASTEXITCODE)." -ForegroundColor Yellow
    Write-Host "       This CPU predates the instruction set the installed build was made for." -ForegroundColor Yellow
    # PyPI has no lower-baseline wheel either: build for this CPU's own instruction set.
    Build-LlamaHere -Reason "Rebuilding llama-cpp-python for this CPU." -CmakeArgs "-DGGML_NATIVE=ON" -IfFailed "the engine installed before stays, and it does not start on this CPU." -Extra @("--force-reinstall", "--no-deps")
    if ($LlamaBuilt -and (Test-VenvPython $StartsHere)) {
        Write-Host "[OK] llama-cpp runtime starts on this CPU (CPU build)." -ForegroundColor Green
        $CpuOnly = $true
        $BuildLabel = "CPU-only (built for this CPU)"
    } else {
        Write-Host "[WARN] llama-cpp still will not start on this CPU." -ForegroundColor Yellow
        Write-Host "       ELI is installed, but inference cannot run until a compatible build exists." -ForegroundColor Yellow
        Write-Host "       Options: add the C++ build tools (above) and run this installer again, or" -ForegroundColor Yellow
        Write-Host "       run ELI in server mode against another machine on your network." -ForegroundColor Yellow
        $CpuOnly = $true
        $BuildWarn = $true
        $BuildLabel = "installed, but does not start on this CPU (see above)"
    }
}

# Verify llama-cpp GPU offload actually compiled in (catch a silent CPU-only wheel).
$Offloads = "import llama_cpp,sys; sys.exit(0 if llama_cpp.llama_supports_gpu_offload() else 1)"
if (-not $CpuOnly) {
    if (Test-VenvPython $Offloads) {
        Write-Host "[OK] llama-cpp-python has CUDA GPU offload." -ForegroundColor Green
    } elseif ($InstallCuda) {
        Write-Host "[WARN] the installed llama-cpp is CPU-only -- installing CUDA toolkit (winget) + rebuilding..." -ForegroundColor Yellow
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            Invoke-Native winget @("install", "--id", "Nvidia.CUDA", "--silent", "--accept-package-agreements", "--accept-source-agreements") -Show | Out-Null
        } else {
            Write-Host "        winget not found -- install the CUDA Toolkit from https://developer.nvidia.com/cuda-downloads" -ForegroundColor Yellow
        }
        # -DGGML_NATIVE=OFF + an explicit /arch: baseline, not cmake's native-detect
        # default -- same reasoning install.sh's _llama_safe_cpu_cmake_flags uses even
        # for a local build: native detection can pick up an instruction set (e.g. on a
        # hybrid P-core/E-core CPU) that is not present on every core, which SIGILLs the
        # moment a thread lands on a core that lacks it. AVX2 is the safe floor.
        Build-LlamaHere -Reason "Rebuilding llama-cpp-python with CUDA." -CmakeArgs "-DGGML_CUDA=on $LlamaCpuFlags" -IfFailed "the CPU engine installed before stays." -Extra @("--force-reinstall", "--no-deps")
        if (Test-VenvPython $Offloads) {
            Write-Host "[OK] llama-cpp-python rebuilt with CUDA." -ForegroundColor Green
            $BuildLabel = "GPU (CUDA, built here)"
        } else {
            Write-Host "[WARN] still CPU-only -- ELI will run on CPU." -ForegroundColor Yellow
            $BuildLabel = "CPU-only (the CUDA build did not compile)"
        }
    } else {
        Write-Host "[WARN] llama-cpp-python is CPU-ONLY -- ELI will be slow. Re-run with -InstallCuda to fix." -ForegroundColor Yellow
        $BuildLabel = "CPU-only (no GPU offload in the installed build)"
    }
}

# ELI v2.0 wheel
Eli-Progress -Phase eli -Pct 55 -Msg "Installing ELI core"
Write-Host "[..] Installing ELI v2.0..."
$Wheel = Get-ChildItem (Join-Path $ScriptDir "dist") -Filter "eli_v2_0-*.whl" -ErrorAction SilentlyContinue | Select-Object -First 1
$EliTarget = if ($Wheel) { @("$($Wheel.FullName)[full]") } else { @("-e", ".[full]") }
# The lock bounds this install too. Without it pip took the newest of everything here and the
# lock replaced it below: the newest Qt's add-on packages stayed behind, built for a Qt no
# longer installed. Where the lock cannot be met on this Python, as before.
$Locked = @()
if ((Split-Path $RequirementsFile -Leaf) -eq "requirements.lock.txt") { $Locked = @("-c", $RequirementsFile) }
Push-Location $ScriptDir
try {
    $EliInstalled = $false
    if ($Locked.Count -gt 0) {
        & $PythonVenv -m pip install @PipFindLinksArgs @EliTarget @Locked --quiet
        $EliInstalled = ($LASTEXITCODE -eq 0)
    }
    if (-not $EliInstalled) { Invoke-Pip (@("install") + $PipFindLinksArgs + $EliTarget + @("--quiet")) }
} finally {
    Pop-Location
}

# Remaining deps. The lock pins versions captured on one Python. Where a pin has no build for
# this one, pip installs none of the set, and that used to end the installer here. As in
# install.sh: the version ranges as a set, then one requirement at a time.
Write-Host "[..] Installing dependencies from $(Split-Path $RequirementsFile -Leaf)..."
& $PythonVenv -m pip install @PipFindLinksArgs -r $RequirementsFile --quiet
if ($LASTEXITCODE -ne 0) {
    $Ranges = Join-Path $ScriptDir "requirements-windows.txt"
    if (-not (Test-Path $Ranges)) { $Ranges = $RequirementsFile }
    Write-Host "[WARN] The dependency set did not install as a whole on Python $pyVer." -ForegroundColor Yellow
    $AsASet = $false
    if ($Ranges -ne $RequirementsFile) {
        Write-Host "[WARN] Retrying with version ranges ($(Split-Path $Ranges -Leaf))." -ForegroundColor Yellow
        & $PythonVenv -m pip install @PipFindLinksArgs -r $Ranges --quiet
        $AsASet = ($LASTEXITCODE -eq 0)
    }
    if (-not $AsASet) {
        Write-Host "[WARN] Installing the requirements one at a time; this takes a few minutes longer." -ForegroundColor Yellow
        & $Python $EnvHelper install-each $ScriptDir $Ranges @PipFindLinksArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[WARN] Some packages could not be installed (named above). ELI runs without them; what uses them is unavailable." -ForegroundColor Yellow
        }
    }
}

# Verify core + GUI imports in the project venv (GUI wheels belong in .venv only).
Write-Host "[..] Verifying installation..."
if (-not (Test-VenvPython "import eli")) {
    throw "'import eli' failed in the virtual environment - the package did not install."
}
$QtWorks = "from eli.gui.qt_compat import real_qt_available; import sys; sys.exit(0 if real_qt_available() else 1)"
if (-not (Test-VenvPython $QtWorks)) {
    Write-Host "[WARN] GUI bindings not importable - installing portable bootstrap into .venv..." -ForegroundColor Yellow
    $Bootstrap = Join-Path $ScriptDir "requirements-portable-bootstrap.txt"
    if (Test-Path $Bootstrap) {
        Invoke-Pip (@("install") + $PipFindLinksArgs + @("-r", $Bootstrap))
    } else {
        Invoke-Pip (@("install") + $PipFindLinksArgs + @("PySide6>=6.6.0"))
    }
    if (Test-VenvPython $QtWorks) {
        Write-Host "[OK] GUI bindings (PySide6) installed in .venv." -ForegroundColor Green
    } else {
        Write-Host "[WARN] PySide6 still not importable - re-run install.ps1 -Yes or use wheelhouse/ offline wheels." -ForegroundColor Yellow
    }
}

# Seed a clean offline config (never overwrite) + init data dirs/databases.
$Settings = Join-Path $ScriptDir "config\settings.json"
$Template = Join-Path $ScriptDir "config\templates\settings.template.json"
if ((-not (Test-Path $Settings)) -and (Test-Path $Template)) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ScriptDir "config") | Out-Null
    Copy-Item $Template $Settings
    Write-Host "[OK] Seeded clean config: config\settings.json" -ForegroundColor Green
}
New-Item -ItemType Directory -Force -Path (Join-Path $ScriptDir "models") | Out-Null
$TemplateDbDir = Join-Path $ScriptDir "config\templates\db"
$ArtifactDbDir = Join-Path $ScriptDir "artifacts\db"
if (Test-Path $TemplateDbDir) {
    New-Item -ItemType Directory -Force -Path $ArtifactDbDir | Out-Null
    $Existing = Get-ChildItem -Path $ArtifactDbDir -Filter "*.sqlite3" -ErrorAction SilentlyContinue
    if (-not $Existing) {
        Copy-Item (Join-Path $TemplateDbDir "*.sqlite3") $ArtifactDbDir -ErrorAction SilentlyContinue
        if (Get-ChildItem -Path $ArtifactDbDir -Filter "*.sqlite3" -ErrorAction SilentlyContinue) {
            Write-Host "[OK] Seeded blank database templates from config\templates\db\" -ForegroundColor Green
        }
    }
}
Write-Host "[..] Initialising data directories and full database architecture..."
# Build EVERY store + table up front (blank slate -- schema only, no personal data).
& $PythonVenv -m eli.core.init_data
if ($LASTEXITCODE -eq 0) { Write-Host "[OK] Full database architecture ready (blank slate)." -ForegroundColor Green }
else { Write-Host "[WARN] Some stores deferred to first launch (self-build on first use)." -ForegroundColor Yellow }

Write-Host "[..] Ensuring capability manifest and command reference..."
# Native (python) non-zero exits do NOT throw in PowerShell, so a try/catch can't see
# them -- check $LASTEXITCODE explicitly (same pattern Invoke-Pip uses).
# No double quote inside the code: PowerShell has no backslash escape, so \" ended the string
# and Python was handed half a line (this step failed on every Windows install).
& $PythonVenv -c "from eli.tools.registry.capability_updater import update_capability_manifest; r=update_capability_manifest(); assert r.get('ok'), r; print('[OK]', r.get('total', 0), 'capabilities indexed')"
if ($LASTEXITCODE -ne 0) {
    if (Test-Path (Join-Path $ScriptDir "capability_manifest.json")) {
        Write-Host "[OK] Using shipped capability_manifest.json (regeneration skipped)." -ForegroundColor Green
    } else {
        Write-Host "[WARN] Capability manifest missing -- run: .venv\Scripts\python -m eli.tools.registry.capability_updater" -ForegroundColor Yellow
    }
}

# -- Optional system tools (best-effort via winget): ffmpeg = media/whisper, tesseract = OCR --
# Non-fatal. Windows uses native APIs for volume/clipboard/notifications, so only these help.
if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "[..] Installing optional system tools (ffmpeg, tesseract) via winget..."
    foreach ($id in @("Gyan.FFmpeg", "UB-Mannheim.TesseractOCR", "mpv.MPV")) {
        Invoke-Native winget @("install", "--id", $id, "--silent", "--accept-package-agreements", "--accept-source-agreements") -Show | Out-Null
    }
    Write-Host "[OK] Optional system tools step done (skips any already present)." -ForegroundColor Green
} else {
    Write-Host "[..] winget not found -- optional: install FFmpeg + Tesseract OCR for media/OCR features." -ForegroundColor DarkGray
}

# -- Optional model download -- the one online step --
$ModelStatus = "none yet"
$existingModel = Get-ChildItem (Join-Path $ScriptDir "models") -Filter "*.gguf" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existingModel) {
    $ModelStatus = "already present"
} elseif ((-not $NoModel) -and ($AutoModel -or $Model -or $ChooseModel)) {
    Write-Host "[..] Model download - the one online step..."
    $modelArg = if ($Model) { $Model } elseif ($ChooseModel) { "--choose" } else { "--auto" }
    & $PythonVenv -m eli.core.model_download $modelArg
    if ($LASTEXITCODE -eq 0) { $ModelStatus = "downloaded" } else { $ModelStatus = "download failed (fetch later)" }
}

# Required support model: the text embedder (memory/RAG). Tiny (~85 MB), not optional;
# fetch it whenever online is allowed, even if a chat model was already present/skipped.
if (-not $NoModel) {
    Write-Host "[..] Ensuring the text embedder (required for memory/RAG) is present..."
    & $PythonVenv -m eli.core.model_download --aux
    if ($LASTEXITCODE -eq 0) { Write-Host "[OK] Embedder ready." -ForegroundColor Green }
    else { Write-Host "[WARN] Embedder fetch deferred (run: python -m eli.core.model_download --aux)" -ForegroundColor Yellow }
}

# Voice weights: required for web-server mic -- always fetch, not gated on chat model.
$VoiceStatus = "skipped"
Write-Host "[..] Ensuring voice models (local STT + TTS, for browser/desktop voice) are present..."
& $PythonVenv -m eli.runtime.voice_assets
if ($LASTEXITCODE -eq 0) { Write-Host "[OK] Voice models ready." -ForegroundColor Green; $VoiceStatus = "ready" }
else { Write-Host "[WARN] Voice models deferred (run: .venv\Scripts\python -m eli.runtime.voice_assets)" -ForegroundColor Yellow; $VoiceStatus = "deferred (fetch later)" }

Eli-Progress -Phase finish -Pct 100 -Msg "Installation complete"
Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host "  ELI v2.0 - installation complete" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
Write-Host ""
Write-Host "--- Summary ---" -ForegroundColor Magenta
if ($BuildWarn) {
    Write-Host "[WARN] Build     llama-cpp $BuildLabel" -ForegroundColor Yellow
} else {
    Write-Host "[OK] Build       llama-cpp $BuildLabel" -ForegroundColor Green
}
Write-Host "[OK] Model       $ModelStatus" -ForegroundColor Green
Write-Host "[OK] Voice       $VoiceStatus" -ForegroundColor Green
Write-Host "[OK] Data        fresh local databases, offline-by-default" -ForegroundColor Green
Write-Host ""
Write-Host "--- Launch ---" -ForegroundColor Magenta
Write-Host "[..] Installing Start Menu shortcuts with ELI icon..."
powershell -ExecutionPolicy Bypass -File "$ScriptDir\scripts\install_desktop_apps.ps1"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARN] Start Menu shortcuts were not added. ELI is installed; add them later with the command below." -ForegroundColor Yellow
}
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
# The installation is complete. Say so to whatever started this script (the graphical
# installer, a build job): without this the result was the last optional step's.
exit 0
