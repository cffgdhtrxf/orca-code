@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Orca Code

echo ======================================
echo   Orca Code - Setup ^& Launch
echo ======================================
echo.

:: ---- Step 1: Check Python version ----
echo [1/6] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo Please install Python 3.10+ from https://python.org
    echo Make sure to check "Add Python to PATH" during install.
    goto :error
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo   Python %%v found
.venv\Scripts\python -c "import sys; exit(0 if sys.version_info>=(3,10) else 1)" 2>nul
if errorlevel 1 (
    python -c "import sys; exit(0 if sys.version_info>=(3,10) else 1)" 2>nul
    if errorlevel 1 (
        echo [ERROR] Python 3.10+ required. Your Python is too old.
        goto :error
    )
)

:: ---- Step 2: Setup venv ----
echo [2/6] Checking virtual environment...
if not exist ".venv\Scripts\python.exe" (
    echo   Creating .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        echo Try: python -m pip install --upgrade pip
        goto :error
    )
    echo   Installing core dependencies...
    .venv\Scripts\python -m pip install -q -r requirements-core.txt
    if errorlevel 1 (
        echo [ERROR] Core dependencies failed to install.
        echo This usually means a network issue or Python version incompatibility.
        echo Try manually: .venv\Scripts\pip install -r requirements-core.txt
        goto :error
    )
)
echo   Virtual environment ready

:: ---- Step 3: Verify core imports ----
echo [3/6] Verifying core dependencies...
.venv\Scripts\python -c "import openai; import tenacity; import requests; import rich; import prompt_toolkit" 2>nul
if errorlevel 1 (
    echo [ERROR] Core import verification failed!
    echo   Reinstalling core dependencies...
    .venv\Scripts\python -m pip install -q -r requirements-core.txt
    .venv\Scripts\python -c "import openai" 2>nul
    if errorlevel 1 (
        echo [ERROR] Core dependencies still broken. Cannot start.
        echo   Try: delete .venv folder and run start.bat again.
        goto :error
    )
)
echo   Core dependencies OK

:: ---- Step 4: Install optional deps (non-blocking) ----
echo [4/6] Installing optional dependencies...
.venv\Scripts\python -m pip install -q -r requirements.txt 2>nul
if errorlevel 1 (
    echo   [WARNING] Some optional packages failed to install - continuing anyway.
    echo   Features like OCR may not be available.
)
echo   Optional dependencies checked

:: ---- Step 5: Check config ----
echo [5/6] Checking configuration...
if not exist "config.json" (
    echo   config.json not found, creating default...
    .venv\Scripts\python -c "import json; json.dump({'api_key':'','base_url':'https://api.deepseek.com','model_name':'deepseek-v4-flash','local_model':False}, open('config.json','w',encoding='utf8'), indent=2, ensure_ascii=False)" 2>nul
    echo   Default config.json created. You will be prompted for API key on first run.
)
echo   Configuration ready

:: ---- Step 6: Quick syntax check ----
echo [6/6] Checking Python files...
.venv\Scripts\python -c "import py_compile; py_compile.compile('orca_code.py', doraise=True)" 2>nul
if errorlevel 1 (
    echo [WARNING] Syntax check failed - but continuing...
) else (
    echo   Syntax OK
)

echo.
echo ======================================
echo   Starting Orca Code...
echo   Type /help for commands
echo   Type /config to change settings
echo ======================================
echo.

:: ---- Launch (keep window open on crash) ----
.venv\Scripts\python orca_code.py
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
        echo   .venv\Scripts\pip install -r requirements-core.txt
        echo   Edit config.json to set your API key
    )
    echo ======================================
)

:error
echo.
pause
