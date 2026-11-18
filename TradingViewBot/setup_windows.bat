@echo off
rem ============================================================
rem  TradingView Analysis Bot - setup for Windows
rem  Double-click this file. Safe to run again at any time.
rem  Installs (only if missing): Python 3.12 and the app's packages,
rem  and puts a "TradingView Bot" shortcut on the desktop.
rem ============================================================
setlocal
cd /d "%~dp0"
echo.
echo === TradingView Analysis Bot setup (Windows) ===
echo.

rem ---------- 0. The folder's path must be short enough ----------
rem Windows limits file paths to 260 characters, and one add-on (torch, for the news) has very long file names.
set "TVB_DIR=%CD%"
powershell -NoProfile -Command "if ($env:TVB_DIR.Length -gt 100) { exit 1 }" >nul 2>&1
if errorlevel 1 goto :path_too_long

rem ---------- 1. Python 3.9 or newer ----------
set "PY="
for %%P in (python py) do if not defined PY %%P -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1 && set "PY=%%P"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PY goto :have_python

echo [1/3] Python not found - installing Python 3.12 ...
where winget >nul 2>&1
if errorlevel 1 goto :no_winget
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" goto :python_failed

:have_python
echo [1/3] Python OK: %PY%

rem ---------- 2. Private environment (.venv) with the app's packages ----------
echo [2/3] Installing the app's packages (this can take a few minutes the first time) ...
if not exist ".venv\Scripts\python.exe" "%PY%" -m venv --clear .venv
if not exist ".venv\Scripts\python.exe" goto :venv_failed
set "VPY=%CD%\.venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%VPY%" -m pip install -r requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 goto :pip_failed
echo       Packages OK

rem ---------- 3. Desktop shortcut to start the app ----------
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'TradingView Bot.lnk')); $s.TargetPath='%CD%\start_app.bat'; $s.WorkingDirectory='%CD%'; $s.Description='Start the TradingView Analysis Bot'; $s.Save()" >nul 2>&1
if not errorlevel 1 echo [3/3] Desktop shortcut "TradingView Bot" created

echo.
echo === Setup complete ===
echo To use the app, double-click "TradingView Bot" on your desktop, or start_app.bat in this folder.
echo.
if /i "%~1"=="--no-launch" goto :eof
start "TradingView Analysis Bot" "%CD%\start_app.bat"
pause
goto :eof

rem ---------- errors ----------
:path_too_long
echo.
echo This folder's location is too long for Windows:
echo   %CD%
echo Move the whole TradingViewBot folder somewhere shorter, for example straight into your Documents
echo folder (C:\Users\your-name\Documents\TradingViewBot), then run this file again from there.
goto :fail
:no_winget
echo.
echo winget is not available on this PC.
echo Install Python 3.12 from https://www.python.org/downloads/ and tick "Add python.exe to PATH",
echo then run this file again.
goto :fail
:python_failed
echo Python install did not complete. Close this window, open a new one and run this file again.
goto :fail
:venv_failed
echo Could not create the .venv folder.
goto :fail
:pip_failed
echo Installing the app's packages failed - check your internet connection and run this file again.
goto :fail
:fail
echo.
pause
exit /b 1
