@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\publish_github.ps1" %*
if errorlevel 1 (
  echo.
  echo Publication did not complete. Review the error above.
  pause
  exit /b 1
)
echo.
pause
