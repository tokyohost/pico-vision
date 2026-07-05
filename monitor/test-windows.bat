@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -m venv .venv
    ) else (
        python -m venv .venv
    )
    if errorlevel 1 goto :error
)

set "PYTHON=.venv\Scripts\python.exe"

echo Installing dependencies...
"%PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed. Retrying without proxy settings...
    set "HTTP_PROXY="
    set "HTTPS_PROXY="
    set "ALL_PROXY="
    set "http_proxy="
    set "https_proxy="
    set "all_proxy="
    set "NO_PROXY=*"
    set "no_proxy=*"
    "%PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)

echo Starting Pico Monitor Windows tray...
"%PYTHON%" -c "from windows_tray import WindowsTrayApplication; raise SystemExit(WindowsTrayApplication(['--worker']).run())"
if errorlevel 1 goto :error

endlocal
exit /b 0

:error
echo.
echo Failed to start the Windows tray application.
pause
endlocal
exit /b 1
