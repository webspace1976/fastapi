@echo off
setlocal enabledelayedexpansion
title FastAPI Environment Setup

:: 1. PATH LOCK: Ensure script runs in its own folder
cd /d "%~dp0"

:: 2. SAFETY CHECK: Prevents running in System32
if /i "%CD%"=="C:\Windows\System32" (
    echo [ERROR] Logic protection triggered! 
    echo Please run this from C:\inetpub\fastapi.
    pause
    exit /b
)

echo =================================================
echo        SETTING UP ENVIRONMENT IN: !CD!
echo =================================================

:: 3. Check for Python
python --version >nul 2>&1
if !errorlevel! neq 0 (
    echo [!] Python not found. Please install Python from python.org.
    pause
    exit /b
)

:: 4. Create Virtual Environment
if not exist "venv" (
    echo [1/3] Creating Virtual Environment (venv)...
    python -m venv venv
) else (
    echo [1/3] venv already exists.
)

:: 5. Install Modern FastAPI Dependencies
echo [2/3] Installing libraries from requirements.txt...
call venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

:: 6. Create Data/Log folders
echo [3/3] Preparing local folders...
if not exist "data" mkdir data
if not exist "logs" mkdir logs

echo =================================================
echo SUCCESS: Environment is ready.
echo To start the app, run: venv\Scripts\python -m uvicorn main:app
echo =================================================
pause