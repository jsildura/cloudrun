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
python run_server.py
pause
