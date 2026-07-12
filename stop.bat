@echo off
REM Dictateur - Stop Script
REM Stops the Python daemon and the AHK hotkey script.
REM Matches on the command line, not just the image name, so unrelated
REM python.exe / AutoHotkey processes are left alone.

cd /d "%~dp0"

powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*daemon.py*' }; if ($p) { $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host ('Daemon stopped (PID ' + $_.ProcessId + ')') } } else { Write-Host 'Daemon not running.' }"

powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'AutoHotkey64.exe' -and $_.CommandLine -like '*hotkey.ahk*' }; if ($p) { $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host ('Hotkey script stopped (PID ' + $_.ProcessId + ')') } } else { Write-Host 'Hotkey script not running.' }"

echo Dictateur stopped.
