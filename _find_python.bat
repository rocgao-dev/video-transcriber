@echo off
rem ====================================================================
rem  Locate a usable Python interpreter (called by launcher scripts).
rem  Usage : call _find_python.bat [module that must be importable]
rem  OK    : env var VTPY = full path, errorlevel = 0
rem  Fail  : VTPY empty, errorlevel = 1
rem  Order (stop at first success):
rem    1) portable  python\python.exe  inside this folder
rem    2) interpreter listed in python_path.txt
rem    3) py launcher
rem    4) python on PATH (Microsoft Store stubs skipped)
rem    5) common dirs  C:\Python3*  %LOCALAPPDATA%\Programs\Python\Python3*
rem  Note: for module "tkinter" a real Tk() window is created once, to make
rem        sure the interpreter can actually open a GUI (broken Tcl is skipped).
rem ====================================================================
setlocal EnableExtensions EnableDelayedExpansion
set "MOD=%~1"
set "FOUND="

echo   [1/5] portable python\python.exe ...
call :try "%~dp0python\python.exe"

echo   [2/5] python_path.txt ...
if not defined FOUND if exist "%~dp0python_path.txt" (
  for /f "usebackq tokens=* delims=" %%P in ("%~dp0python_path.txt") do (
    set "LINE=%%P"
    if not "!LINE:~0,1!"=="#" if not defined FOUND call :try "%%P"
  )
)

echo   [3/5] py launcher ...
if not defined FOUND for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do call :try "%%P"

echo   [4/5] python on PATH ...
if not defined FOUND for /f "delims=" %%P in ('where python 2^>nul') do (
  set "PP=%%P"
  if "!PP:WindowsApps=!"=="!PP!" call :try "%%P"
)

echo   [5/5] common install folders ...
if not defined FOUND for /f "delims=" %%D in ('dir /b /ad "C:\Python3*" 2^>nul') do call :try "C:\%%D\python.exe"
if not defined FOUND for /f "delims=" %%D in ('dir /b /ad "%LOCALAPPDATA%\Programs\Python\Python3*" 2^>nul') do call :try "%LOCALAPPDATA%\Programs\Python\%%D\python.exe"
if not defined FOUND for /f "delims=" %%D in ('dir /b /ad "C:\Program Files\Python3*" 2^>nul') do call :try "C:\Program Files\%%D\python.exe"
echo   done.

if defined FOUND (
  endlocal & set "VTPY=%FOUND%" & exit /b 0
)
endlocal & set "VTPY=" & exit /b 1

:try
if defined FOUND goto :eof
if not exist "%~1" goto :eof
if not defined MOD goto :accept
if /i "%MOD%"=="tkinter" goto :try_tk
"%~1" -c "import importlib.util as u,sys;sys.exit(0 if u.find_spec('%MOD%') else 1)" >nul 2>nul
if errorlevel 1 goto :eof
goto :accept
:try_tk
"%~1" -c "import tkinter;r=tkinter.Tk();r.destroy()" >nul 2>nul
if errorlevel 1 goto :eof
:accept
set "FOUND=%~1"
goto :eof