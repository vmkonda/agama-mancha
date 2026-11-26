@echo off
rem Runs auto-redeploy.ps1 without changing Windows' script policy (a one-off bypass for this script only).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0auto-redeploy.ps1" %*
exit /b %ERRORLEVEL%
