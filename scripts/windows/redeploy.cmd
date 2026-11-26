@echo off
rem Runs redeploy.ps1 without changing Windows' script policy (a one-off bypass for this script only).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0redeploy.ps1" %*
exit /b %ERRORLEVEL%
