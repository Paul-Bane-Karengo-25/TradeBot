@echo off
rem Shows how the logged picks (the Track record) have done, without opening the app. Read-only.
setlocal
cd /d "%~dp0"
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=%CD%\.venv\Scripts\python.exe"
if not defined PY for %%P in (python py) do if not defined PY %%P -c "import sys" >nul 2>&1 && set "PY=%%P"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY (
  echo Python was not found. Run setup_windows.bat first.
  pause
  exit /b 1
)
"%PY%" check_track_record.py
set "RESULT=%ERRORLEVEL%"
if /i not "%~1"=="--no-pause" pause
exit /b %RESULT%
