@echo off
rem Runs auto-sync.ps1 without changing Windows' script policy (a one-off bypass for this script only).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0auto-sync.ps1" %*
exit /b %ERRORLEVEL%
