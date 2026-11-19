@echo off
rem PNGtuber Studio installer: double-click to install or repair. Safe to run again.
rem The work is done by scripts\install\install.ps1; a log is written to install.log.
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install\install.ps1"
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
