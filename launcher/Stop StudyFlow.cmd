@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-studyflow.ps1"
if errorlevel 1 (
    echo.
    echo StudyFlow could not stop completely. See the message above.
    pause
    exit /b 1
)
exit /b 0
