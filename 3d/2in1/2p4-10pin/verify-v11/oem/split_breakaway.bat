@echo off
setlocal EnableDelayedExpansion

set "OPENSCAD=C:\Program Files (x86)\OpenSCAD\openscad.com"
set "SCAD=%~dp0cad_breakaway.scad"
set "OUT=%~dp0"

echo ========================================
echo OpenSCAD 3MF Split Export - Breakaway
echo ========================================
echo.

if not exist "%OPENSCAD%" goto :openscad_not_found
if not exist "%SCAD%" goto :scad_not_found

echo SCAD:
echo %SCAD%
echo.

echo [1/3] Exporting front_shell...
"%OPENSCAD%" -o "%OUT%01_front_shell.3mf" -D "part=\"front_shell\"" "%SCAD%"
if errorlevel 1 goto :error

echo.
echo [2/3] Exporting back_cover...
"%OPENSCAD%" -o "%OUT%02_back_cover.3mf" -D "part=\"back_cover\"" "%SCAD%"
if errorlevel 1 goto :error

echo.
echo [3/3] Exporting screen + ESP32 breakaway pair...
"%OPENSCAD%" -o "%OUT%03_04_screen_esp32_breakaway.3mf" -D "part=\"screen_esp32_breakaway_pair\"" "%SCAD%"
if errorlevel 1 goto :error

echo.
echo ========================================
echo SUCCESS
echo ========================================
echo Generated:
echo %OUT%01_front_shell.3mf
echo %OUT%02_back_cover.3mf
echo %OUT%03_04_screen_esp32_breakaway.3mf
echo.
pause
exit /b 0


:openscad_not_found
echo.
echo ERROR: OpenSCAD not found.
echo Path:
echo "%OPENSCAD%"
echo.
pause
exit /b 1


:scad_not_found
echo.
echo ERROR: cad_breakaway.scad not found.
echo Expected:
echo "%SCAD%"
echo.
pause
exit /b 1


:error
echo.
echo ========================================
echo ERROR: OpenSCAD export failed!
echo ========================================
pause
exit /b 1