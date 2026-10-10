@echo off
cd /d "%~dp0"
title Video Transcriber - Simple UI

rem  Simple UI uses only the standard library (tkinter).
rem  The probe verifies the interpreter can really open a GUI window.
call "%~dp0_find_python.bat" tkinter
if errorlevel 1 (
  echo.
  echo [ERROR] No Python with a working tkinter was found.
  echo         Please install Python 3.9+ from https://www.python.org/downloads/
  echo         and tick "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)

rem  quick syntax check of the script (no side effects)
"%VTPY%" -c "import ast;ast.parse(open(r'%~dp0ui_simple.py',encoding='utf-8').read())"
if errorlevel 1 (
  echo.
  echo [ERROR] ui_simple.py failed to load ^(see message above^).
  echo         Details are also written to ui_error.log in this folder.
  echo.
  pause
  exit /b 1
)

rem  launch with pythonw so no black console window is left open
set "PYW=%VTPY%"
for %%F in ("%VTPY%") do set "PYDIR=%%~dpF"
if exist "%PYDIR%pythonw.exe" set "PYW=%PYDIR%pythonw.exe"
start "" "%PYW%" "%~dp0ui_simple.py"
echo Simple UI started. If no window appears, open ui_error.log in this folder.
timeout /t 2 >nul