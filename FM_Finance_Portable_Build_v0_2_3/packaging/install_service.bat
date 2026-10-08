@echo off
rem Installs FM Finance as a Windows service using NSSM - https://nssm.cc
rem Run as Administrator from the folder that contains FMExpenseTracker.exe.
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

if not exist "%DIR%\FMExpenseTracker.exe" goto :no_exe
if not exist "%DIR%\.env" goto :no_env
if not exist "%DIR%\logs" mkdir "%DIR%\logs"

"%NSSM%" install %SERVICE% "%DIR%\FMExpenseTracker.exe"
if errorlevel 1 goto :install_failed
"%NSSM%" set %SERVICE% AppDirectory "%DIR%"
"%NSSM%" set %SERVICE% DisplayName "F&M Finance"
"%NSSM%" set %SERVICE% Description "F&M IT Services expense tracking"
rem Delayed start gives PostgreSQL and MinIO time to come up after a reboot.
"%NSSM%" set %SERVICE% Start SERVICE_DELAYED_AUTO_START
"%NSSM%" set %SERVICE% AppStdout "%DIR%\logs\service.log"
"%NSSM%" set %SERVICE% AppStderr "%DIR%\logs\service.log"
"%NSSM%" set %SERVICE% AppRotateFiles 1
"%NSSM%" set %SERVICE% AppRotateBytes 10485760
"%NSSM%" set %SERVICE% AppExit Default Restart
"%NSSM%" set %SERVICE% AppRestartDelay 15000
"%NSSM%" set %SERVICE% AppStopMethodConsole 15000
"%NSSM%" start %SERVICE%

echo.
echo Service %SERVICE% installed and started. Logs are in the logs folder next to the .exe.
echo To allow other computers to connect, open the port in Windows Firewall, for example:
echo   netsh advfirewall firewall add rule name="FM Finance" dir=in action=allow protocol=TCP localport=8010
exit /b 0

:not_admin
echo ERROR: Run this script as Administrator.
exit /b 1
:no_nssm
echo ERROR: nssm.exe not found. Put it on PATH or in the same folder as this script.
exit /b 1
:no_exe
echo ERROR: FMExpenseTracker.exe must be in the same folder as this script.
exit /b 1
:no_env
echo ERROR: Create .env from .env.example in this folder before installing the service.
exit /b 1
:install_failed
echo ERROR: Service install failed. If it is already installed, run uninstall_service.bat first.
exit /b 1
