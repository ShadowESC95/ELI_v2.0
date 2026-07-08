@echo off
REM ELI v2.0 — Windows launcher
setlocal
set SCRIPT_DIR=%~dp0
set VENV=%SCRIPT_DIR%.venv
set ELI_PROJECT_ROOT=%SCRIPT_DIR%
if not defined ELI_DATA_DIR set ELI_DATA_DIR=%SCRIPT_DIR%artifacts
if not defined ELI_CONFIG_DIR set ELI_CONFIG_DIR=%SCRIPT_DIR%config
if not defined ELI_MODELS_DIR set ELI_MODELS_DIR=%SCRIPT_DIR%models
if not defined ELI_CACHE_DIR set ELI_CACHE_DIR=%SCRIPT_DIR%cache
if defined PYTHONPATH (set PYTHONPATH=%SCRIPT_DIR%;%PYTHONPATH%) else (set PYTHONPATH=%SCRIPT_DIR%)

if not exist "%VENV%\Scripts\python.exe" (
    echo [ELI] Virtual environment not found. Run install.bat first.
    pause
    exit /b 1
)

"%VENV%\Scripts\python.exe" -m eli %*
