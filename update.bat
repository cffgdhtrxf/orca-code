@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title Orca Code Updater

echo ======================================
echo   Orca Code Update Tool
echo ======================================
echo.

:: Step 1: Check git
echo [1/3] Checking Git...
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Git not found. Install from https://git-scm.com
    pause
    exit /b 1
)
git --version 2>&1 | findstr /i "git" >nul
echo   OK

:: Step 2: Fetch remote
echo [2/3] Fetching remote...
git fetch origin --quiet
if %errorlevel% neq 0 (
    echo ERROR: Cannot connect to GitHub. Check your network/proxy.
    pause
    exit /b 1
)
echo   OK

:: Step 3: Compare and pull
echo [3/3] Checking for updates...

for /f %%v in ('git rev-parse HEAD') do set LOCAL=%%v
for /f %%v in ('git rev-parse origin/main') do set REMOTE=%%v

if "%LOCAL%"=="%REMOTE%" (
    echo   Already up to date (%LOCAL:~0,8%^)
    echo.
    echo ======================================
    echo   No update needed
    echo ======================================
    timeout /t 3 >nul
    exit /b 0
)

echo   Local:  %LOCAL:~0,8%
echo   Remote: %REMOTE:~0,8%
echo.
echo   Changes:
git log %LOCAL%..origin/main --oneline --no-decorate 2>nul
echo.

:: Stash local changes
git stash --include-untracked --quiet 2>nul
set STASHED=0
git stash list 2>nul | findstr "." >nul && set STASHED=1

:: Pull
echo   Pulling updates...
git pull origin main --ff-only --quiet 2>nul
if %errorlevel% neq 0 (
    echo   Fast-forward failed, trying hard reset...
    git fetch origin --quiet
    git reset --hard origin/main --quiet
    if %errorlevel% neq 0 (
        echo ERROR: Update failed. Please check manually.
        pause
        exit /b 1
    )
)

:: Restore stashed changes
if %STASHED% equ 1 (
    echo   Restoring local changes...
    git stash pop --quiet 2>nul
)

echo.
echo ======================================
echo   Update complete
echo ======================================
echo.
echo   Updated to %REMOTE:~0,8%
echo   Run start.bat to launch.
echo.
echo   If dependencies changed, reinstall:
echo     pip install -e .
echo.
pause
