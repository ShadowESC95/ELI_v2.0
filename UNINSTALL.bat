@echo off
REM ELI uninstaller (Windows) — double-click to remove ELI.
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\uninstall.ps1"
echo.
pause
