@echo off
setlocal enabledelayedexpansion
title FastAPI GitHub Sync - Secure Version

:: 1. FORCE THE SCRIPT TO STAY IN ITS OWN FOLDER
:: %~dp0 is the directory where this .bat file lives
cd /d "%~dp0"

:: 2. SAFETY CHECK: Ensure we are NOT in System32
if /i "%CD%"=="C:\Windows\System32" (
    echo [ERROR] Logic protection triggered! 
    echo This script was about to run in System32.
    echo Please move this .bat to C:\inetpub\fastapi and run it there.
    pause
    exit /b
)

echo =================================================
echo        GITHUB SYNC: !CD!
echo =================================================

:: 3. CONFIGURATION
:: Replace these with your actual details
set REPO_URL=https://github.com/webspace1976/fastapi
set BRANCH=main

:: 4. GIT PERMISSION FIX
:: This tells Git to trust this specific folder on your company machine
git config --local safe.directory "!CD!"

:: 5. INITIALIZE IF FIRST TIME
if not exist ".git" (
    echo [!] Initializing Git repository in current folder...
    git init -b %BRANCH%
    git remote add origin %REPO_URL%
)

:: 6. REFRESH IDENTITY (Ensures it uses your GitHub user, not Domain user)
:: Change these to your actual GitHub info
git config user.name "webspace1976"
git config user.email "webspace1976@msn.com"

:: 7. PULL / STAGE / COMMIT / PUSH
echo [1/3] Fetching latest changes from GitHub...
git pull origin %BRANCH%

echo [2/3] Staging files...
git add .

set /p commit_msg="Enter description of changes (or press Enter for Auto-sync): "
if "%commit_msg%"=="" set commit_msg=Auto-sync !date! !time!

git commit -m "%commit_msg%"

echo [3/3] Uploading to GitHub...
git push origin %BRANCH%

echo =================================================
echo SUCCESS: Project synced safely.
echo =================================================
pause