@echo off
cd /d "%~dp0"
title Video Transcriber - Install dependencies

echo ============================================================
echo   One-time install / update of runtime dependencies (needs internet)
echo ============================================================
echo.
echo [1/3] Detecting a Python interpreter ...
call "%~dp0_find_python.bat"
if errorlevel 1 (
  echo.
  echo [ERROR] No Python interpreter found.
  echo         Please install Python 3.9+ and tick "Add python.exe to PATH".
  echo         Download: https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)
echo       Found: %VTPY%
echo.
echo [2/3] Installing dependencies (first run may take several minutes) ...
"%VTPY%" -m pip install --upgrade pip --disable-pip-version-check --timeout 30 --retries 3
"%VTPY%" -m pip install -r "%~dp0requirements.txt" --disable-pip-version-check --timeout 30 --retries 3
echo.
echo [3/3] Verifying:
"%VTPY%" -c "import faster_whisper, numpy; print('  faster-whisper / numpy  OK')"
"%VTPY%" -c "import imageio_ffmpeg; print('  imageio-ffmpeg        OK')"
echo.
echo If there is no error above, the installation succeeded.
echo You can now double-click the Simple UI .bat or the Web UI .bat.
echo.
pause