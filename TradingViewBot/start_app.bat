@echo off
rem ============================================================
rem  TradingView Analysis Bot - start the app in your web browser
rem  Double-click this file (or the "TradingView Bot" desktop shortcut).
rem  Keep the black window open while you use the app; close it to stop.
rem ============================================================
setlocal
cd /d "%~dp0"
title TradingView Analysis Bot
if not exist ".venv\Scripts\python.exe" (
  echo First-time setup is needed - this takes a few minutes ...
  call "%~dp0setup_windows.bat" --no-launch
)
set "VPY=%CD%\.venv\Scripts\python.exe"
if not exist "%VPY%" goto :fail
"%VPY%" -c "import streamlit, tradingview_ta" >nul 2>&1
if errorlevel 1 "%VPY%" -m pip install --quiet --disable-pip-version-check -r requirements.txt

cls
echo.
echo   ===============================================================
echo    TradingView Analysis Bot is starting...
echo    Your web browser will open as soon as the app is ready
echo    (the first start can take up to a minute).
echo.
echo    If it doesn't, open your browser and go to:  http://localhost:8501
echo.
echo    KEEP THIS WINDOW OPEN while you use the app.
echo    Close this window to stop the app.
echo   ===============================================================
echo.
rem open the browser only once the app answers (checks every second, for up to 90 seconds)
start "" powershell -NoProfile -WindowStyle Hidden -Command "for ($i = 0; $i -lt 90; $i++) { try { if ((Invoke-WebRequest 'http://127.0.0.1:8501/_stcore/health' -UseBasicParsing -Proxy $null -TimeoutSec 2).Content -eq 'ok') { break } } catch {}; Start-Sleep 1 }; Start-Process 'http://localhost:8501'"
"%VPY%" -m streamlit run app.py
echo.
echo The app has stopped.
pause
goto :eof

:fail
echo.
echo Setup did not complete. Run setup_windows.bat and try again.
pause
exit /b 1
