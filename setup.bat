@echo off
rem Double-click to install Ask 2 Learn (venv, dependencies, shortcuts, autostart) and start it.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
echo.
pause
