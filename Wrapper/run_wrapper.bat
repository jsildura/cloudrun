@echo off
setlocal

set WRAPPER_DIR=%~dp0

echo ============================================
echo   gamdl Wrapper Setup
echo ============================================
echo.

:: Check for argument
if "%1"=="login" goto :login
if "%1"=="run" goto :run
if "%1"=="stop" goto :stop
if "%1"=="" goto :run

:login
echo.
echo Building wrapper image...
docker build -t gamdl-wrapper "%WRAPPER_DIR%."
if errorlevel 1 goto :docker_error

echo.
echo ============================================
echo   Enter your Apple Music credentials when prompted.
echo   This only needs to be done ONCE.
echo ============================================
echo.
docker run -it -v "%WRAPPER_DIR%rootfs\data:/app/rootfs/data" -e args="-L %2 -H 0.0.0.0" gamdl-wrapper
goto :end

:run
echo Starting wrapper service...
docker rm -f gamdl-wrapper-instance 2>nul
docker run -d --name gamdl-wrapper-instance -v "%WRAPPER_DIR%rootfs\data:/app/rootfs/data" -p 10020:10020 -p 20020:20020 -p 30020:30020 -e args="-H 0.0.0.0" gamdl-wrapper
if errorlevel 1 goto :docker_error

timeout /t 3 >nul
docker ps --filter name=gamdl-wrapper-instance --format "Status: {{.Status}}" 2>nul
echo.
echo Wrapper is running! Ports: 10020, 20020, 30020
echo You can now enable "Use Wrapper" in gamdl settings.
goto :end

:stop
echo Stopping wrapper...
docker rm -f gamdl-wrapper-instance 2>nul
echo Stopped.
goto :end

:docker_error
echo.
echo ERROR: Docker command failed. Make sure Docker Desktop is running.

:end
pause
