@echo off
SETLOCAL

:: 1. SET PATHS
:: Points to the Portable Git executable on your U: drive [cite: 4]
set "GIT_EXE=%cd%\tools\PortableGit\bin\git.exe"

:: 2. SET GITHUB DETAILS
:: Replace these with your actual GitHub username and repository name

set "REPO_URL=https://github.com/webspace1976/fastapi.git"

:: 3. VERIFY GIT EXECUTABLE EXISTS
if not exist "%GIT_EXE%" (
    echo [ERROR] Portable Git not found at %GIT_EXE% [cite: 4, 5]
    pause
    exit /b
)

:: 4. MOVE TO PROJECT DIRECTORY
:: Navigates into the FastAPI project folder [cite: 4]
cd /d "%cd%\fastapi-main"

:: 5. AUTO-INIT IF .GIT IS MISSING
:: Initializes the repo if it was previously just a downloaded ZIP [cite: 5]
if not exist ".git" (
    echo [INFO] .git folder not found. Initializing repository...
    "%GIT_EXE%" init
    "%GIT_EXE%" remote add origin %REPO_URL%
    echo [SUCCESS] Repository linked to %REPO_URL%
)

echo Checking for updates from GitHub...

:: 6. PERFORM THE UPDATE
:: 'fetch' followed by 'reset' ensures local network drive changes don't cause conflicts
"%GIT_EXE%" fetch origin main
"%GIT_EXE%" reset --hard origin/main

if %ERRORLEVEL% EQU 0 (
    echo [SUCCESS] Code is up to date. [cite: 4]
) else (
    echo [ERROR] Git update failed. Check network or credentials. [cite: 5]
)

pause