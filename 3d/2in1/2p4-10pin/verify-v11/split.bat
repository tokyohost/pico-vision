@echo off
setlocal

set "OPENSCAD=C:\Program Files (x86)\OpenSCAD\openscad.com"
set "SCAD=E:\WorkSpace\fn-vision\pico-project\3d\2in1\2p4-10pin\verify-v11\cad.scad"
set "OUT=%~dp0"

echo ========================================
echo OpenSCAD 3MF Split Export
echo ========================================

echo [1/4] front_shell
"%OPENSCAD%" -o "%OUT%01_front_shell.3mf" -D "part=\"front_shell\"" "%SCAD%"
if errorlevel 1 goto :error

echo [2/4] back_cover
"%OPENSCAD%" -o "%OUT%02_back_cover.3mf" -D "part=\"back_cover\"" "%SCAD%"
if errorlevel 1 goto :error

echo [3/4] screen_clamp_bar
"%OPENSCAD%" -o "%OUT%03_screen_clamp_bar.3mf" -D "part=\"screen_clamp_bar\"" "%SCAD%"
if errorlevel 1 goto :error

echo [4/4] esp32_usb_clamp_bar
"%OPENSCAD%" -o "%OUT%04_esp32_usb_clamp_bar.3mf" -D "part=\"esp32_usb_clamp_bar\"" "%SCAD%"
if errorlevel 1 goto :error

echo.
echo ========================================
echo ALL 4 FILES EXPORTED SUCCESSFULLY
echo Output:
echo %OUT%
echo ========================================
pause
exit /b 0

:error
echo.
echo ========================================
echo ERROR: OpenSCAD export failed!
echo ========================================
pause
exit /b 1