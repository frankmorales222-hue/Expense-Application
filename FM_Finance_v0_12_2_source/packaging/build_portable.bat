@echo off
setlocal
cd /d "%~dp0.."

echo.
echo ========================================
echo   F^&M Finance - Portable EXE Builder
echo ========================================
echo.

rem Use 64-bit Python 3.12 exactly (Windows launcher, PATH, then the bundled workspace runtime).
set "PYEXE="
where py >nul 2>nul && py -3.12 -c "import sys,struct; sys.exit(0 if sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8 else 1)" >nul 2>nul && set "PYEXE=py -3.12"
if not defined PYEXE (
    where python >nul 2>nul && python -c "import sys,struct; sys.exit(0 if sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8 else 1)" >nul 2>nul && set "PYEXE=python"
)
if not defined PYEXE (
    if exist "..\Python312\python.exe" "..\Python312\python.exe" -c "import sys,struct; sys.exit(0 if sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8 else 1)" >nul 2>nul && set "PYEXE=..\Python312\python.exe"
)
if not defined PYEXE goto :no_python
%PYEXE% -c "import sys,struct; sys.exit(0 if sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8 else 1)" || goto :bad_python
where npm >nul 2>nul || goto :no_node

echo [1/5] Building web interface...
pushd frontend
call npm ci || (popd & goto :fail)
call npm run build || (popd & goto :fail)
popd

echo [2/5] Preparing build environment...
rem Recreate .venv if it was made with a different Python version.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys,struct; sys.exit(0 if sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8 else 1)" || rmdir /s /q .venv
)
if not exist ".venv\Scripts\python.exe" %PYEXE% -m venv .venv || goto :fail
".venv\Scripts\python.exe" -m pip install -r backend\requirements-portable.txt pyinstaller==6.22.3 pytest==8.3.4 httpx==0.28.1 --quiet || goto :fail
".venv\Scripts\python.exe" -c "import sys, sqlalchemy; print('Python:', sys.version.split()[0]); print('SQLAlchemy:', sqlalchemy.__version__)" || goto :fail

echo [3/5] Running tests...
pushd backend
set "TEST_DATABASE_URL=sqlite:///data/fm_finance_test.db"
"..\.venv\Scripts\python.exe" -m pytest -q || (popd & goto :fail)
popd

for /f "tokens=2 delims==" %%V in ('findstr /b "__version__" backend\app\__init__.py') do set "APPVER=%%~V"
set "APPVER=%APPVER: =%"
set APPVER=%APPVER:"=%
rem The EXE must carry the public half of this PC's update signing key (see packaging\make_update.py).
if exist "%USERPROFILE%\.fmfinance\update_signing_key.pem" ".venv\Scripts\python.exe" packaging\make_update.py keygen || goto :fail
echo [4/5] Building single FMFinance.exe (version %APPVER%)...
".venv\Scripts\python.exe" -m PyInstaller packaging\fm_finance_portable.spec --noconfirm --clean --distpath portable-output --workpath build-portable || goto :fail

echo [5/5] Making the signed update file...
if not exist "%USERPROFILE%\.fmfinance\update_signing_key.pem" goto :no_key
".venv\Scripts\python.exe" packaging\make_update.py build || goto :fail
".venv\Scripts\python.exe" packaging\make_update.py verify "update-output\FMFinance_Update_v%APPVER%.fmupdate" || goto :fail
goto :done
:no_key
echo NOTE: No update signing key on this PC, so no update file was made.
echo       One time only: .venv\Scripts\python.exe packaging\make_update.py keygen   then build again.

:done
echo.
echo SUCCESS
echo Full program (first install, or a new PC):  portable-output\FMFinance.exe
echo Update file (Administration ^> Updates):     update-output\FMFinance_Update_v%APPVER%.fmupdate
echo.
if not defined FMFINANCE_NO_EXPLORER explorer portable-output
exit /b 0

:no_python
echo ERROR: Install 64-bit Python 3.12 from python.org (tick "Add python.exe to PATH").
pause
exit /b 1
:bad_python
echo ERROR: 64-bit Python 3.12 is required. Install it from python.org; other versions can stay installed.
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
