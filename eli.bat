@echo off
REM ELI v2.0 — Windows launcher
setlocal
set SCRIPT_DIR=%~dp0
set VENV=%SCRIPT_DIR%.venv

if not exist "%VENV%\Scripts\python.exe" (
    echo [ELI] Virtual environment not found. Run install.bat first.
    pause
    exit /b 1
)

"%VENV%\Scripts\python.exe" -m eli %*
