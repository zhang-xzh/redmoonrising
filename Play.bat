@echo off
setlocal EnableExtensions

rem One-click launcher, driven from the server checkout like EveJS' Play.bat:
rem start the redmoonrising compose stack, wait for the game port, then start
rem the 3913 client. Moved here from the client directory so a single script
rem covers the whole local loop.
rem
rem Usage:
rem     Play.bat              start the server and the client
rem     Play.bat --no-client  start the server only
rem
rem Environment overrides:
rem     RMR_CLIENT_DIR        client directory (default below)
rem
rem docker-compose.yml pins the project name to "rmr", so every checkout drives
rem the same containers. Running this from a worktree therefore recreates them
rem from that worktree's tree; the main checkout stays the normal place to run it.

set "RMR_DIR=%~dp0"
if "%RMR_DIR:~-1%"=="\" set "RMR_DIR=%RMR_DIR:~0,-1%"

if not defined RMR_CLIENT_DIR set "RMR_CLIENT_DIR=M:\EVE-LOCAL\inputs\EVE-Online-3913"

set "PLAY_SERVER_ONLY=0"
if /i "%~1"=="--no-client" set "PLAY_SERVER_ONLY=1"

echo [1/3] Starting redmoonrising from "%RMR_DIR%" ...
pushd "%RMR_DIR%" || goto :no_dir
docker compose up -d
if errorlevel 1 (
    popd
    echo.
    echo Failed to start redmoonrising.
    echo If port 26000 or 5432 is busy, stop EveJS first:
    echo     docker stop evejs-server-1
    pause
    exit /b 1
)
popd

echo [2/3] Waiting for 127.0.0.1:26000 ...
powershell -NoProfile -Command "$end=(Get-Date).AddMinutes(5); while((Get-Date) -lt $end){ try{ $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',26000); $c.Close(); exit 0 }catch{ Start-Sleep -Milliseconds 500 } }; exit 1"
if errorlevel 1 (
    echo Server did not open port 26000. Check logs with:
    echo     docker compose logs server --tail 100
    pause
    exit /b 1
)

if "%PLAY_SERVER_ONLY%"=="1" (
    echo [3/3] Skipping client ^(--no-client^).
    exit /b 0
)

if not exist "%RMR_CLIENT_DIR%\eve.exe" (
    echo.
    echo Client not found: "%RMR_CLIENT_DIR%\eve.exe"
    echo Set RMR_CLIENT_DIR to the client directory and run Play.bat again.
    pause
    exit /b 1
)

echo [3/3] Launching client from "%RMR_CLIENT_DIR%" ...
rem Always show the CCP-internal "Local Servers" entry on the login screen.
set "USERDOMAIN=CENTRAL"
pushd "%RMR_CLIENT_DIR%" || goto :no_dir
start "" "%RMR_CLIENT_DIR%\eve.exe"
popd
exit /b 0

:no_dir
echo Directory not found.
pause
exit /b 1
