@echo off
REM ELI MKXI - Windows installer (delegates to the full-featured PowerShell installer)
REM   install.bat            -> CUDA install from the frozen lock + GPU verify + DB init
REM   install.bat /cpu       -> CPU-only
REM   install.bat /cuda      -> also auto-install the CUDA toolkit (winget) if missing
REM   install.bat /latest    -> version ranges instead of the frozen lock
setlocal
set SCRIPT_DIR=%~dp0
set PS_ARGS=

:parse
if "%~1"=="" goto run
if /I "%~1"=="/cpu"           set PS_ARGS=%PS_ARGS% -CpuOnly
if /I "%~1"=="--cpu-only"     set PS_ARGS=%PS_ARGS% -CpuOnly
if /I "%~1"=="/cuda"          set PS_ARGS=%PS_ARGS% -InstallCuda
if /I "%~1"=="--install-cuda" set PS_ARGS=%PS_ARGS% -InstallCuda
if /I "%~1"=="/latest"        set PS_ARGS=%PS_ARGS% -Latest
shift
goto parse

:run
where powershell >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Windows PowerShell is required to install ELI MKXI.
    pause
    exit /b 1
)
echo [..] Launching the ELI MKXI PowerShell installer...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%install.ps1"%PS_ARGS%
set RC=%ERRORLEVEL%
if not "%ELI_INSTALLER_UNATTENDED%"=="1" pause
exit /b %RC%
