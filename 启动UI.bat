@echo off
cd /d "%~dp0"
title Video Transcriber - Web UI

rem  Needs a Python with faster-whisper installed; auto-detected, no paths.
call "%~dp0_find_python.bat" faster_whisper
if errorlevel 1 (
  echo.
  echo [ERROR] No Python with the required packages was found.
  echo         Please double-click the "install dependencies" .bat once first,
  echo         or install Python 3.9+ from https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

echo Starting web UI ^(the browser opens automatically^)...
echo Keep this window open; closing it stops the service.
"%VTPY%" -u "%~dp0app_web.py" %*
pause