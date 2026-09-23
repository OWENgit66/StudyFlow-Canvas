@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-studyflow.ps1"
if errorlevel 1 (
    echo.
    echo StudyFlow could not start. See the message above and the project logs folder.
    pause
    exit /b 1
)
exit /b 0
