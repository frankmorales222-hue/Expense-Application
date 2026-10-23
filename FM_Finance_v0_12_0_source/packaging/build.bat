@echo off
rem Builds dist\FMExpenseTracker\FMExpenseTracker.exe. Run from anywhere; it switches to the project root.
setlocal
cd /d "%~dp0.."

echo.
echo [1/5] Checking prerequisites
where python >nul 2>nul
if errorlevel 1 goto :no_python
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 goto :old_python
where npm >nul 2>nul
if errorlevel 1 goto :no_node

echo.
echo [2/5] Building the frontend
pushd frontend
call npm ci
if errorlevel 1 (popd & set "STEP=npm ci" & goto :fail)
call npm run build
if errorlevel 1 (popd & set "STEP=frontend build" & goto :fail)
popd

echo.
echo [3/5] Preparing the Python environment
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 (set "STEP=create virtual environment" & goto :fail)
)
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt pyinstaller==6.11.1 --quiet
if errorlevel 1 (set "STEP=pip install" & goto :fail)

echo.
echo [4/5] Building the executable
".venv\Scripts\python.exe" -m PyInstaller packaging\fm_expense_tracker.spec --noconfirm --clean --distpath dist --workpath build
if errorlevel 1 (set "STEP=PyInstaller" & goto :fail)

echo.
echo [5/5] Copying configuration and service scripts
copy /y .env.example dist\FMExpenseTracker\.env.example >nul
copy /y packaging\install_service.bat dist\FMExpenseTracker\ >nul
copy /y packaging\uninstall_service.bat dist\FMExpenseTracker\ >nul
if not exist dist\FMExpenseTracker\logs mkdir dist\FMExpenseTracker\logs

echo.
echo Build complete: dist\FMExpenseTracker\FMExpenseTracker.exe
echo Next: copy .env.example to .env in that folder, fill it in, then run the .exe.
exit /b 0

:no_python
echo ERROR: Python was not found on PATH. Install Python 3.11 or newer and tick "Add python.exe to PATH".
exit /b 1
:old_python
echo ERROR: Python 3.11 or newer is required.
exit /b 1
:no_node
echo ERROR: Node.js was not found on PATH. Install Node.js 20 LTS or newer.
exit /b 1
:fail
echo.
echo ERROR: Build failed during step: %STEP%
exit /b 1
