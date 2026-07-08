@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title Orca Code Updater

echo ======================================
echo   Orca Code Update Tool
echo ======================================
echo.

if exist ".git" goto :git_update

::  ZIP download mode (no git) — use absolute PowerShell path for systems where it's not in PATH
set "PWSH=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PWSH%" set "PWSH=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"

echo [1/2] Checking PowerShell...
if not exist "%PWSH%" (
    echo ERROR: PowerShell required but not found at %PWSH%
    pause
    exit /b 1
)
echo   OK

set TEMP_ZIP=%TEMP%\orca-update.zip
set TEMP_DIR=%TEMP%\orca-update

echo [2/2] Downloading latest version from GitHub...
echo   URL: https://github.com/cffgdhtrxf/orca-code/archive/main.zip

"%PWSH%" -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Write-Host '   Downloading...'; (New-Object System.Net.WebClient).DownloadFile('https://github.com/cffgdhtrxf/orca-code/archive/main.zip', '%TEMP_ZIP%'); Write-Host '   Extracting...'; if (Test-Path '%TEMP_DIR%') { Remove-Item '%TEMP_DIR%' -Recurse -Force }; Expand-Archive '%TEMP_ZIP%' -DestinationPath '%TEMP_DIR%'; Write-Host '   SUCCESS'; exit 0 } catch { Write-Host '   FAILED: ' + $_.Exception.Message; exit 1 }"
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Download failed. Check your network connection.
    pause
    exit /b 1
)

:: Find the extracted folder (GitHub adds '-main' suffix to the folder name)
set SRC=%TEMP_DIR%\orca-code-main

:: Check for version info
if exist "%SRC%\VERSION" (
    type "%SRC%\VERSION"
)

:: Copy: orca_code\ (core package), start.bat, config.example.json, pyproject.toml, etc.
echo   Applying update...
echo.
:: robocopy: copy all files and dirs except user data (config, db, venv, etc.)
robocopy "%SRC%" "." /E /NDL /NFL /NJH /NJS /XF "config.json" "*.db" "*.db-shm" "*.db-wal" /XD ".git" ".venv" "save" "memory" "__pycache__" ".pytest_cache" ".ruff_cache" ".cache" "target" 2>nul

:: Clean up temp files
del "%TEMP_ZIP%" >nul 2>&1
rmdir /S /Q "%TEMP_DIR%" >nul 2>&1

echo ======================================
echo   Update complete
echo ======================================
echo.
echo   Run start.bat to launch.
echo.
goto :end

::  Git mode 
:git_update
echo [1/3] Checking Git...
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Git not found. Install from https://git-scm.com
    pause
    exit /b 1
)
echo   OK

echo [2/3] Fetching updates...
git fetch origin --quiet
if %errorlevel% neq 0 (
    echo ERROR: Cannot connect to GitHub. Check your network/proxy.
    pause
    exit /b 1
)
echo   OK

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

git stash --include-untracked --quiet 2>nul
git pull origin main --ff-only --quiet 2>nul
if %errorlevel% neq 0 (
    echo   Fast-forward failed, using hard reset...
    git fetch origin --quiet
    git reset --hard origin/main --quiet
)
git stash pop --quiet 2>nul

echo.
echo ======================================
echo   Update complete
echo ======================================
echo.
echo   Updated to %REMOTE:~0,8%

:end
echo   Run start.bat to launch.
echo.
echo   If dependencies changed, reinstall:
echo     pip install -e .
echo.
pause
