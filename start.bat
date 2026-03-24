@echo off
REM Achilles Diktator — Start Script
REM Starts Python daemon and AHK hotkey script

cd /d "%~dp0"

REM Activate venv
call venv\Scripts\activate.bat

REM Start daemon in background
start /B "" python daemon.py

REM Wait for daemon to be ready (check if port 9876 is listening)
echo Waiting for daemon...
set /a ATTEMPTS=0
:wait_loop
timeout /t 1 /nobreak >nul
set /a ATTEMPTS+=1
if %ATTEMPTS% GEQ 30 (
    echo ERROR: Daemon did not start within 30 seconds.
    exit /b 1
)
powershell -Command "Test-NetConnection -ComputerName localhost -Port 9876 -InformationLevel Quiet" | findstr /C:"True" >nul 2>&1
if errorlevel 1 goto wait_loop
echo Daemon ready.

REM Start AHK script (GUI process, no console window)
start "" "hotkey.ahk"

echo Achilles Diktator running.
