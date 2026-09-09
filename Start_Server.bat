@echo off
title gamdl Web Server
cd /d "%~dp0"
echo Starting gamdl web server...
echo.
echo Access from this PC:   http://localhost:8000
echo Access from mobile:    http://%COMPUTERNAME%:8000
echo.
echo Press Ctrl+C to stop the server.
echo.
set "PYTHON_BIN=python"
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_BIN=%~dp0.venv\Scripts\python.exe"
)

if exist "%~dp0bin" set "PATH=%~dp0bin;%PATH%"

"%PYTHON_BIN%" run_server.py
pause
