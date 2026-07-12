@echo off
REM Dictateur — Start Script
REM Starts Python daemon and AHK hotkey script

cd /d "%~dp0"

REM Optional: point the daemon at a custom-vocabulary markdown file.
REM See README.md → "Custom vocabulary" for the expected format.
REM set DICTATEUR_VOCABULARY_PATH=%USERPROFILE%\Documents\archilles-dictateur\vocabulary.md

REM Optional: override the Whisper model (default: medium / int8_float16, ~0.75 GB VRAM).
REM Larger model = better recognition, more VRAM (~2 GB for large-v3-turbo int8_float16).
REM set DICTATEUR_MODEL_SIZE=large-v3-turbo
REM set DICTATEUR_COMPUTE_TYPE=int8_float16

REM Optional: minutes of idle time before the model releases its VRAM (default: 5).
REM Set to 0 to keep the model resident for the whole session.
REM set DICTATEUR_IDLE_UNLOAD_MINUTES=10

REM Start daemon in background (expliziter venv-Pfad)
start /B "" "%~dp0venv\Scripts\python.exe" "%~dp0daemon.py"

REM Wait for daemon to be ready (check if port 9876 is listening)
echo Waiting for daemon...
set /a ATTEMPTS=0
:wait_loop
REM ping, not timeout: timeout aborts when stdin is redirected (e.g. when the
REM script is launched from a non-console context).
ping -n 2 127.0.0.1 >nul
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

echo Dictateur running.
