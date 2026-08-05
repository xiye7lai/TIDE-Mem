@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  set /p TIDE_BASE_URL=Enter the public HTTPS base URL, for example https://tide-mem.onrender.com: 
  if "%TIDE_BASE_URL%"=="" (
    echo Base URL is required.
    pause
    exit /b 2
  )
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\verify_hosted.ps1" -BaseUrl "%TIDE_BASE_URL%"
) else (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\verify_hosted.ps1" %*
)
if errorlevel 1 (
  echo.
  echo Hosted verification did not complete. Review the error above.
  pause
  exit /b 1
)
echo.
pause
