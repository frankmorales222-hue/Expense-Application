@echo off
rem Stops and removes the FM Finance Windows service. Run as Administrator.
setlocal
set "SERVICE=FMExpenseTracker"
set "DIR=%~dp0"
set "DIR=%DIR:~0,-1%"

net session >nul 2>&1
if errorlevel 1 goto :not_admin

set "NSSM="
if exist "%DIR%\nssm.exe" set "NSSM=%DIR%\nssm.exe"
if not defined NSSM for %%I in (nssm.exe) do set "NSSM=%%~$PATH:I"
if not defined NSSM goto :no_nssm

"%NSSM%" stop %SERVICE%
"%NSSM%" remove %SERVICE% confirm
echo Service %SERVICE% removed. Data in PostgreSQL and MinIO is untouched.
exit /b 0

:not_admin
echo ERROR: Run this script as Administrator.
exit /b 1
:no_nssm
echo ERROR: nssm.exe not found. Put it on PATH or in the same folder as this script.
exit /b 1
