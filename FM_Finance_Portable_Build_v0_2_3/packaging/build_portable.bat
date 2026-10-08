@echo off
setlocal
cd /d "%~dp0.."

echo.
echo ========================================
echo   F&M Finance - Portable EXE Builder
echo ========================================
echo.

where python >nul 2>nul || goto :no_python
python -c "import sys,struct; sys.exit(0 if sys.version_info >= (3,11) and struct.calcsize('P') == 8 else 1)" || goto :bad_python
where npm >nul 2>nul || goto :no_node

echo [1/3] Building web interface...
pushd frontend
call npm ci || (popd & goto :fail)
call npm run build || (popd & goto :fail)
popd

echo [2/3] Preparing build environment...
if not exist ".venv\Scripts\python.exe" python -m venv .venv || goto :fail
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet || goto :fail
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt pyinstaller==6.11.1 --quiet || goto :fail

echo [3/3] Building single FMFinance.exe...
".venv\Scripts\python.exe" -m PyInstaller packaging\fm_finance_portable.spec --noconfirm --clean --distpath portable-output --workpath build-portable || goto :fail

echo.
echo SUCCESS
 echo Your app is here:
 echo   portable-output\FMFinance.exe
 echo.
explorer portable-output
exit /b 0

:no_python
echo ERROR: Install 64-bit Python 3.11 or newer and select "Add Python to PATH".
pause
exit /b 1
:bad_python
echo ERROR: 64-bit Python 3.11 or newer is required.
pause
exit /b 1
:no_node
echo ERROR: Install Node.js 20 LTS or newer.
pause
exit /b 1
:fail
echo.
echo BUILD FAILED. Review the messages above.
pause
exit /b 1
