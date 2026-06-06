@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Orca Code

echo ======================================
echo   Orca Code - Setup ^& Launch
echo ======================================
echo.

:: ---- Step 1: Check Python ----
echo [1/5] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo Please install Python 3.10+ from https://python.org
    echo Make sure to check "Add Python to PATH" during install.
    goto :error
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo   Python %%v found

:: ---- Step 2: Setup venv ----
echo [2/5] Checking virtual environment...
if not exist ".venv\Scripts\python.exe" (
    echo   Creating .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        echo Try: python -m pip install --upgrade pip
        goto :error
    )
    echo   Installing core dependencies...
    .venv\Scripts\python -m pip install -q -r requirements.txt
    if errorlevel 1 (
        echo [WARNING] Some packages failed to install.
        echo Try manually: .venv\Scripts\pip install -r requirements.txt
    )
)
echo   Virtual environment ready

:: ---- Step 3: Check config ----
echo [3/5] Checking configuration...
if not exist "config.json" (
    echo   config.json not found, creating default...
    .venv\Scripts\python -c "import json; json.dump({'api_key':'','base_url':'https://api.deepseek.com','model_name':'deepseek-chat','local_model':False}, open('config.json','w',encoding='utf8'), indent=2, ensure_ascii=False)" 2>nul
    echo   Default config.json created. You will be prompted for API key on first run.
)
echo   Configuration ready

:: ---- Step 4: Quick syntax check ----
echo [4/5] Checking Python files...
.venv\Scripts\python -c "import py_compile; py_compile.compile('ultimate_agent.py', doraise=True)" 2>nul
if errorlevel 1 (
    echo [WARNING] Syntax check failed - but continuing...
) else (
    echo   Syntax OK
)

:: ---- Step 5: Install optional deps ----
echo [5/5] Checking optional packages...
.venv\Scripts\python -c "import ipython" 2>nul
if errorlevel 1 (
    echo   [Optional] Installing ipython for better REPL...
    .venv\Scripts\pip install -q ipython 2>nul
)
echo.
echo ======================================
echo   Starting Orca Code...
echo   Type /help for commands
echo   Type /config to change settings
echo ======================================
echo.

:: ---- Launch (keep window open on crash) ----
.venv\Scripts\python ultimate_agent.py
set EXITCODE=%errorlevel%

if %EXITCODE% neq 0 (
    echo.
    echo ======================================
    echo [EXIT CODE: %EXITCODE%]
    echo.
    if %EXITCODE% equ 1 (
        echo Common causes:
        echo   - Missing or invalid API key
        echo   - API server unreachable
        echo   - Missing dependencies
        echo.
        echo Try:
        echo   .venv\Scripts\pip install -r requirements.txt
        echo   Edit config.json to set your API key
    )
    echo ======================================
)

:error
echo.
pause
