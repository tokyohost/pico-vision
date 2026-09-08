@echo off
setlocal
cd /d "%~dp0"
if exist "..\..\.venv\Scripts\python.exe" (
  "..\..\.venv\Scripts\python.exe" "production_gui.py"
) else (
  python "production_gui.py"
)
if errorlevel 1 pause
