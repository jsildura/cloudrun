@echo off
setlocal

echo ============================================
echo   gamdl - Local Server + Cloudflare Tunnel
echo ============================================
echo.

:: Check if cloudflared is available (in project directory or PATH)
set "CLOUDFLARED_BIN=cloudflared"
if exist "%~dp0cloudflared.exe" (
    set "CLOUDFLARED_BIN=%~dp0cloudflared.exe"
) else (
    where cloudflared >nul 2>nul
    if errorlevel 1 (
        echo ERROR: cloudflared is not installed.
        echo Install it with: winget install Cloudflare.cloudflared
        echo or place cloudflared.exe directly in this folder: %~dp0
        pause
        exit /b 1
    )
)

:: Check if Python is available (in .venv or PATH)
set "PYTHON_BIN=python"
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_BIN=%~dp0.venv\Scripts\python.exe"
)

if exist "%~dp0bin" set "PATH=%~dp0bin;%PATH%"

:: Start the gamdl server in the background
echo Starting gamdl server on port 8080...
start "gamdl-server" cmd /c "cd /d %~dp0 && "%PYTHON_BIN%" run_server.py --host 0.0.0.0 --port 8080"

:: Wait for server to start
timeout /t 3 /nobreak >nul

:: Start Cloudflare Tunnel (quick tunnel, no account needed)
echo.
echo Starting Cloudflare Tunnel...
echo.
echo ============================================
echo   IMPORTANT: Look for the tunnel URL below!
echo   It will look like: https://xxxxx.trycloudflare.com
echo.
echo   Copy that URL and add it as API_URL in your
echo   Cloudflare Workers dashboard:
echo   Settings > Variables and Secrets > Add
echo ============================================
echo.

"%CLOUDFLARED_BIN%" tunnel --url http://localhost:8080

:: When tunnel is closed (Ctrl+C), also stop the server
echo.
echo Shutting down server...
taskkill /FI "WINDOWTITLE eq gamdl-server" /F >nul 2>nul
echo Done.
pause
