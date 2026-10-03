@echo off
REM ============================================================================
REM  ErgoCare - start everything for a demo (Windows). Double-click, or:
REM     start_demo.bat          real wearable (ESP32 on USB)
REM     start_demo.bat demo     DEMO MODE - simulated wearable "DEMO-01"
REM  Opens three windows (backend, app, wearable) and then the browser.
REM  Close those windows to stop. Everything runs locally - no Wi-Fi needed
REM  (voice recognition in Chrome still needs internet).
REM ============================================================================
cd /d "%~dp0"
set "ROOT=%~dp0"
set "PY=%ROOT%ergo_ml_backend\.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo [!] Backend is not set up yet. See README.md - "Setup", step 1.
  pause
  exit /b 1
)
if not exist "%ROOT%node_modules" (
  echo [!] App is not set up yet. Run:  npm install   ^(see README.md^)
  pause
  exit /b 1
)

REM /d sets each window's folder - the backend must run inside ergo_ml_backend
REM because its database, uploads and .env live there.
echo Starting ErgoCare backend...
start "ErgoCare backend" /d "%ROOT%ergo_ml_backend" cmd /k ""%PY%" -m uvicorn app.main:app --port 8000"

echo Starting ErgoCare app...
start "ErgoCare app" /d "%ROOT%" cmd /k "npm run dev -- --port 5173"

if /i "%~1"=="demo" (
  echo Starting DEMO wearable simulator ^(DEMO-01^)...
  start "ErgoCare DEMO wearable" /d "%ROOT%firmware" cmd /k ""%PY%" demo_simulator.py"
) else (
  echo Starting USB bridge for the ESP32 wearable...
  start "ErgoCare wearable (USB)" /d "%ROOT%firmware" cmd /k ""%PY%" usb_bridge.py"
)

echo Waiting for the servers...
timeout /t 8 /nobreak >nul
start "" "http://localhost:5173"
echo Done. ErgoCare is open in your browser.
