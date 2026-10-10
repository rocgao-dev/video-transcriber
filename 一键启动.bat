@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Video Transcriber - One-Click Start

echo ============================================================
echo   Video Transcriber  -  One-Click Start
echo   (detect Python - install deps - download model - open UI)
echo ============================================================
echo.

echo [1/4] Detecting a Python interpreter ...
call "%~dp0_find_python.bat"
if errorlevel 1 goto nopy
set "PY=%VTPY%"
echo       Found: %PY%
echo.

echo [2/4] Checking dependencies ...
"%PY%" -c "import faster_whisper, numpy" >nul 2>nul
if errorlevel 1 (
  echo       Installing ... first run may take several minutes, needs internet
  "%PY%" -m pip install --upgrade pip --disable-pip-version-check --timeout 30 --retries 3
  "%PY%" -m pip install -r "%~dp0requirements.txt" --disable-pip-version-check --timeout 30 --retries 3
  "%PY%" -c "import faster_whisper, numpy" >nul 2>nul
  if errorlevel 1 (
    echo.
    echo [ERROR] Dependency installation failed.
    echo         Run the dependency installer bat and read its output, then retry.
    echo.
    pause
    exit /b 1
  )
) else (
  echo       Dependencies OK
)
echo.

echo [3/4] Checking the model ...
if exist "%~dp0models\small\model.bin" (
  echo       Model OK
) else (
  echo       Model not found - downloading now ... about 480 MB, one time
  if not exist "%~dp0models\small" mkdir "%~dp0models\small"
  where curl >nul 2>nul
  if errorlevel 1 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://modelscope.cn/models/pengzhendong/faster-whisper-small/resolve/master/model.bin' -OutFile '%~dp0models\small\model.bin'"
  ) else (
    curl -L --fail -o "%~dp0models\small\model.bin" "https://modelscope.cn/models/pengzhendong/faster-whisper-small/resolve/master/model.bin"
  )
  if not exist "%~dp0models\small\model.bin" (
    echo.
    echo [ERROR] Model download failed. Check your network and retry.
    echo.
    pause
    exit /b 1
  )
)
echo.

echo [4/4] Opening the Simple UI ...
call "%~dp0_find_python.bat" tkinter
if errorlevel 1 (
  echo.
  echo [ERROR] No Python with a working tkinter was found.
  echo         Install Python 3.9+ from https://www.python.org/downloads/
  echo         and tick "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)
set "PYW=%VTPY%"
for %%F in ("%VTPY%") do set "PYDIR=%%~dpF"
if exist "%PYDIR%pythonw.exe" set "PYW=%PYDIR%pythonw.exe"
start "" "%PYW%" "%~dp0ui_simple.py"
echo Simple UI started.
timeout /t 2 >nul
exit /b 0

:nopy
echo.
echo [ERROR] No Python interpreter found.
echo         Install Python 3.9+ from https://www.python.org/downloads/
echo         and tick "Add python.exe to PATH", then run this again.
echo.
pause
exit /b 1