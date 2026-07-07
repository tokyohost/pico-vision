@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (set "PYTHON=.venv\Scripts\python.exe") else (set "PYTHON=python")
"%PYTHON%" -m pip install -r requirements.txt -r requirements-build.txt
if errorlevel 1 exit /b 1
"%PYTHON%" -m PyInstaller --clean --noconfirm pico_monitor.spec
if errorlevel 1 exit /b 1
set "ISCC=ISCC.exe"
where "%ISCC%" >nul 2>nul
if errorlevel 1 (
  if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
    set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
  ) else (
    echo 未找到 Inno Setup ISCC.exe，已生成中间 EXE：dist\pico-monitor.exe
    echo 请安装 Inno Setup 后重新执行本脚本生成安装包。
    exit /b 1
  )
)
"%ISCC%" /DAppVersion=development /DArchitecture=x64 /DSourceExe=dist\pico-monitor.exe pico_monitor_setup.iss
if errorlevel 1 exit /b 1
echo Windows 安装包已生成：dist\OmniWatch-windows-x64-setup-vdevelopment.exe
endlocal
