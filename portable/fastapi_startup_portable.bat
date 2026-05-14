@echo off
SETLOCAL

:: 1. SET PATHS
:: We use %cd% to refer to the current folder where this .bat sits
set "VENV_PYTHON=%cd%\fastapi-main\venv\Scripts\python.exe"
set PORT=8080

:: 2. PERFORMANCE TWEAKS FOR NETWORK DRIVE
set PYTHONDONTWRITEBYTECODE=1
set PYTHONUNBUFFERED=1

:: 3. VERIFY VENV EXISTS
if not exist "%VENV_PYTHON%" (
    echo [ERROR] Virtual environment not found at %VENV_PYTHON%
    echo Please run your install/setup script first.
    pause
    exit /b
)


echo Stopping existing FastAPI processes on port %PORT%...
:: This finds the Process ID (PID) using the port and kills it
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :%PORT%') do taskkill /f /pid %%a 2>nul

echo Starting FastAPI using VENV...
echo Project: %cd%\fastapi-main

cd /d "%cd%\fastapi-main"

:: 4. RUN UVICORN
:: Calling it via the venv python ensures all your installed libs are found
"%VENV_PYTHON%" -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload

pause