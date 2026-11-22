@echo off
rem Double-click to start Ask 2 Learn from source (no build needed). Extra arguments are passed on, e.g. --now.
rem Its one message comes from the language files, through setup.ps1 -Say.
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -Say setup.no_venv
    pause
    exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py" %*
