@echo off
setlocal

echo ============================================
echo   gamdl - Local Server + Cloudflare Tunnel
echo ============================================
echo.

:: Check if cloudflared is installed
where cloudflared >nul 2>nul
if errorlevel 1 (
    echo ERROR: cloudflared is not installed.
    echo Install it with: winget install Cloudflare.cloudflared
    pause
    exit /b 1
)

:: Start the gamdl server in the background
echo Starting gamdl server on port 8080...
start "gamdl-server" cmd /c "cd /d %~dp0 && uv run uvicorn server.main:app --host 0.0.0.0 --port 8080 --workers 1"

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

cloudflared tunnel --url http://localhost:8080

:: When tunnel is closed (Ctrl+C), also stop the server
echo.
echo Shutting down server...
taskkill /FI "WINDOWTITLE eq gamdl-server" /F >nul 2>nul
echo Done.
pause
