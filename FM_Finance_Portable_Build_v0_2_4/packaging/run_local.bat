@echo off
setlocal
cd /d "%~dp0.."
where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Install Python 3.11 or newer and add it to PATH.
    exit /b 1
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
if errorlevel 1 exit /b 1
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
if errorlevel 1 exit /b 1
if not exist "frontend\dist\index.html" (
    echo Frontend build missing. Install Node.js 20 or newer if npm is unavailable.
    pushd frontend
    call npm ci
    if errorlevel 1 (popd & exit /b 1)
    call npm run build
    if errorlevel 1 (popd & exit /b 1)
    popd
)
if not exist .env (
    powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File packaging\configure.ps1 -AppDirectory "%CD%"
    if errorlevel 1 exit /b 1
)
echo.
echo Open http://127.0.0.1:8010 after startup completes, unless APP_PORT was changed.
echo Keep this window open. Press Ctrl+C to stop the test app.
cd backend
"..\.venv\Scripts\python.exe" run.py
exit /b %errorlevel%
