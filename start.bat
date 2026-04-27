@echo off
REM LOGOS ASF — Windows one-click start (batch fallback)

echo.
echo --------------------------------------------------
echo   LOGOS ASF -- Sprint 5 deploy (Windows)
echo --------------------------------------------------
echo.

where docker >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Docker Desktop not found.
    echo Install from https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)

if not exist ".abigail.env" (
    echo [WARN] .abigail.env not found. Abigail will start in offline mode.
    echo.
)

echo Starting containers...
docker compose up --build -d
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] docker compose failed.
    pause
    exit /b 1
)

echo.
echo Stack is up.
echo.
echo   Operator Console : http://localhost:7070/dashboard
echo   Intent Compiler  : http://localhost:7070/intake
echo   Sentinel health  : http://localhost:9090/health
echo.
echo   Logs:  docker compose logs -f
echo   Stop:  docker compose down
echo.

timeout /t 2 /nobreak >nul
start http://localhost:7070/dashboard
