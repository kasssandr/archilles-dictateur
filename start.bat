@echo off
REM Archilles Diktator — Start Script
REM Starts Python daemon and AHK hotkey script

cd /d "%~dp0"

REM Start daemon in background (expliziter venv-Pfad)
start /B "" "%~dp0venv\Scripts\python.exe" "%~dp0daemon.py"

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
netstat -an | findstr "127.0.0.1:9876" >nul 2>&1
if errorlevel 1 goto wait_loop
echo Daemon ready.

REM Start AHK script (GUI process, no console window)
set AHK="%LOCALAPPDATA%\Programs\AutoHotkey\v2\AutoHotkey64.exe"
start "" %AHK% "%~dp0hotkey.ahk"

echo Archilles Diktator running.
