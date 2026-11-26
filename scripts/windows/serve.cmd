@echo off
rem Runs serve.ps1 without changing Windows' script policy (a one-off bypass for this script only).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0serve.ps1" %*
exit /b %ERRORLEVEL%
