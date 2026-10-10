@echo off
cd /d "%~dp0"
title Video Transcriber - Download model

set "URL=https://modelscope.cn/models/pengzhendong/faster-whisper-small/resolve/master/model.bin"
set "OUT=%~dp0models\small\model.bin"

echo ============================================================
echo   Download faster-whisper "small" model  (about 480 MB)
echo   Source: ModelScope  pengzhendong/faster-whisper-small
echo   Target: models\small\model.bin
echo ============================================================
echo.
if not exist "%~dp0models\small" mkdir "%~dp0models\small"

where curl >nul 2>nul
if %errorlevel%==0 (
  echo Downloading with curl ...
  curl -L --fail -o "%OUT%" "%URL%"
) else (
  echo Downloading with PowerShell ...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri '%URL%' -OutFile '%OUT%'"
)

echo.
if exist "%OUT%" (
  for %%F in ("%OUT%") do echo Done. Size: %%~zF bytes
  echo Model saved to models\small\model.bin
) else (
  echo [ERROR] Download failed. Check your network and retry, or download
  echo         model.bin manually from the ModelScope link above.
)
echo.
pause