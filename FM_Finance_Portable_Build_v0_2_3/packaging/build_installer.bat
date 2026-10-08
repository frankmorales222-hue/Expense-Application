@echo off
setlocal
cd /d "%~dp0.."
set "ISCC="
for %%I in (ISCC.exe) do set "ISCC=%%~$PATH:I"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC (
    echo ERROR: Install Inno Setup 6.3 or newer from https://jrsoftware.org/isdl.php
    echo Or put ISCC.exe on PATH. This is only needed on the build computer.
    exit /b 1
)
python -c "import struct,sys; sys.exit(0 if struct.calcsize('P') == 8 else 1)"
if errorlevel 1 (
    echo ERROR: This installer requires 64-bit Python 3.11 or newer on Windows.
    exit /b 1
)
call packaging\build.bat
if errorlevel 1 exit /b 1
"%ISCC%" packaging\installer.iss
if errorlevel 1 (
    echo ERROR: The application built, but installer compilation failed.
    exit /b 1
)
echo.
echo Installer ready: installer-output\FM_Finance_Setup_v0.2.2.exe
exit /b 0
