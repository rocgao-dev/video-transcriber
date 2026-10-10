@echo off
cd /d "%~dp0"
setlocal

if "%~1"=="" (
  echo Usage: drag a video/audio file onto THIS .bat icon to get a transcript.
  echo Example: drag  D:\video.mp4  onto this .bat.
  echo.
  echo Or run from a command prompt:
  echo   "%~nx0" "D:\video.mp4"
  echo.
  echo ^(Double-clicking without a file just shows this help - that is normal.^)
  pause
  exit /b 1
)

rem  auto-detect a Python with the dependencies (no hard-coded paths)
call "%~dp0_find_python.bat" faster_whisper
if errorlevel 1 (
  echo.
  echo [ERROR] No Python with the required packages was found.
  echo         Please double-click the "install dependencies" .bat once first.
  echo.
  pause
  exit /b 1
)

echo Transcribing: %~1
echo.
"%VTPY%" -u "%~dp0transcribe.py" "%~1" --timestamps
echo.
echo Done. The transcript .txt is saved next to the source file.
pause