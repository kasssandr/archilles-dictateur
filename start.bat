@echo off
REM Archilles Dictator — Start Script
REM Starts Python daemon and AHK hotkey script

cd /d "%~dp0"

REM Optional: point the daemon at a custom-vocabulary markdown file.
REM See README.md → "Custom vocabulary" for the expected format.
REM set ARCHILLES_VOCABULARY_PATH=%USERPROFILE%\Documents\archilles-dictator\vocabulary.md

REM Optional: override the Whisper model (default: small / float16).
REM Larger model = better recognition, more VRAM (~2 GB for large-v3-turbo int8_float16).
REM set ARCHILLES_MODEL_SIZE=large-v3-turbo
REM set ARCHILLES_COMPUTE_TYPE=int8_float16

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

echo Archilles Dictator running.
