@echo off
REM ELI MKXI — Windows installer
REM Run from PowerShell or Command Prompt with Admin rights if needed

setlocal enabledelayedexpansion
set SCRIPT_DIR=%~dp0
set VENV=%SCRIPT_DIR%.venv
set "ELI_INSTALL_UNATTENDED=0"
if /I "%~1"=="/unattended" set "ELI_INSTALL_UNATTENDED=1"
if /I "%~1"=="--unattended" set "ELI_INSTALL_UNATTENDED=1"
if "%ELI_INSTALLER_UNATTENDED%"=="1" set "ELI_INSTALL_UNATTENDED=1"

echo ==============================
echo   ELI MKXI Installer (Windows)
echo ==============================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.11+ not found. Download from https://python.org/downloads/
    echo         Make sure to check "Add Python to PATH" during installation.
    if not "%ELI_INSTALL_UNATTENDED%"=="1" pause
    exit /b 1
)
echo [OK] Python found:
python --version
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] ELI MKXI for Windows requires Python 3.11 or newer.
    if not "%ELI_INSTALL_UNATTENDED%"=="1" pause
    exit /b 1
)

REM Create venv
if exist "%VENV%\Scripts\activate.bat" (
    echo [OK] Virtual environment already exists.
) else (
    echo [..] Creating virtual environment...
    python -m venv "%VENV%"
)

set PIP=%VENV%\Scripts\pip.exe
set PYTHON_VENV=%VENV%\Scripts\python.exe
set "REQ_FILE=%SCRIPT_DIR%requirements-windows.txt"
if not exist "%REQ_FILE%" if exist "%SCRIPT_DIR%requirements.txt" set "REQ_FILE=%SCRIPT_DIR%requirements.txt"
if not exist "%REQ_FILE%" (
    echo [ERROR] Could not find requirements-windows.txt or requirements.txt in %SCRIPT_DIR%
    if not "%ELI_INSTALL_UNATTENDED%"=="1" pause
    exit /b 1
)

set "WHEELHOUSE="
if exist "%SCRIPT_DIR%wheelhouse\*.whl" set "WHEELHOUSE=%SCRIPT_DIR%wheelhouse"
if not defined WHEELHOUSE if exist "%SCRIPT_DIR%dist\wheelhouse\*.whl" set "WHEELHOUSE=%SCRIPT_DIR%dist\wheelhouse"
set "PIP_WHEELHOUSE_ARGS=--prefer-binary"
if defined WHEELHOUSE (
    echo [OK] Using bundled wheelhouse: %WHEELHOUSE%
    set PIP_WHEELHOUSE_ARGS=--find-links "%WHEELHOUSE%" --prefer-binary
)

echo [..] Upgrading pip...
"%PIP%" install --quiet --upgrade pip setuptools wheel || goto :install_failed

REM Install PyTorch — detect CUDA
echo [..] Installing PyTorch...
echo     For CUDA GPU acceleration, run this manually after install:
echo     pip install torch --index-url https://download.pytorch.org/whl/cu121
echo     For CPU-only:
echo     pip install torch --index-url https://download.pytorch.org/whl/cpu
echo.
echo     Proceeding with CPU version for compatibility...
"%PIP%" install %PIP_WHEELHOUSE_ARGS% torch --index-url https://download.pytorch.org/whl/cpu --quiet || goto :install_failed

REM Install llama-cpp-python
echo [..] Installing llama-cpp-python (CPU)...
echo     For CUDA GPU acceleration, run manually:
echo     pip install llama-cpp-python --prefer-binary --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
"%PIP%" install %PIP_WHEELHOUSE_ARGS% llama-cpp-python --quiet || goto :install_failed

REM Install ELI MKXI
echo [..] Installing ELI MKXI...
set "ELI_WHEEL="
for %%f in ("%SCRIPT_DIR%dist\eli_mkxi-*.whl") do (
    if exist "%%~f" set "ELI_WHEEL=%%~f"
)
if defined ELI_WHEEL (
    "%PIP%" install %PIP_WHEELHOUSE_ARGS% "%ELI_WHEEL%[full]" --quiet || goto :install_failed
) else (
    "%PIP%" install %PIP_WHEELHOUSE_ARGS% -e "%SCRIPT_DIR%[full]" --quiet || goto :install_failed
)

REM Install remaining dependencies
echo [..] Installing remaining dependencies...
"%PIP%" install %PIP_WHEELHOUSE_ARGS% -r "%REQ_FILE%" --quiet || goto :install_failed

echo.
echo ==============================
echo   Installation complete!
echo ==============================
echo.
echo Launch ELI with:
echo   eli.bat
echo.
"%PYTHON_VENV%" -c "from eli.core.paths import models_dir; print('Models location: ' + str(models_dir()))" 2>nul
if errorlevel 1 echo Models location: use the app data models directory or set ELI_MODELS_DIR
echo.
if not "%ELI_INSTALL_UNATTENDED%"=="1" pause
exit /b 0

:install_failed
echo.
echo [ERROR] Installation failed. Review the pip output above.
echo.
if not "%ELI_INSTALL_UNATTENDED%"=="1" pause
exit /b 1
