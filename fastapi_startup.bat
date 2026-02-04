@echo off
set PORT=8080
cd /d "C:\inetpub\fastapi"

echo [1/3] Stopping existing FastAPI processes on port %PORT%...
:: This finds the Process ID (PID) using the port and kills it
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :%PORT%') do taskkill /f /pid %%a 2>nul

echo [2/3] Cleaning up any hanging python processes...
taskkill /f /im python.exe /t 2>nul

echo [3/3] Starting FastAPI...
echo ---------------------------------------------------
:: Running without --reload for manual execution stability
:: python.exe -m uvicorn main:app --host 0.0.0.0 --port %PORT%
C:\inetpub\fastapi\venv\Scripts\python -m uvicorn main:app --reload --host 0.0.0.0 --port %PORT%

