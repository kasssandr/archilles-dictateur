@echo off
REM Archilles Diktator — Stop Script
REM Beendet Daemon und AHK-Script

REM AHK-Prozess beenden
taskkill /F /IM AutoHotkey64.exe >nul 2>&1
taskkill /F /IM AutoHotkey32.exe >nul 2>&1

REM Daemon beenden (sucht nach python daemon.py)
for /f "tokens=1" %%p in ('wmic process where "CommandLine like '%%daemon.py%%'" get ProcessId /value 2^>nul ^| findstr ProcessId') do (
    set PID=%%p
)
if defined PID (
    taskkill /F /PID %PID:~10% >nul 2>&1
)

REM Alternativ: alle python-Prozesse die daemon.py laufen haben
powershell -Command "Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*daemon.py*' } | Stop-Process -Force" >nul 2>&1

echo Archilles Diktator gestoppt.
