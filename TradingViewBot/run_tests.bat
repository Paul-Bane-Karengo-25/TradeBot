@echo off
rem Runs the full automated test of the app (about 30 seconds, offline, doesn't touch your portfolio).
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
"%PY%" tests\run_tests.py
set "RESULT=%ERRORLEVEL%"
if /i not "%~1"=="--no-pause" pause
exit /b %RESULT%
