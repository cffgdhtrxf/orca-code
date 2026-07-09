@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [Setup] Creating virtual environment...
    python -m venv .venv
    echo [Setup] Installing core dependencies...
    .venv\Scripts\pip install -q -r requirements-core.txt
    if errorlevel 1 (
        echo [ERROR] Core dependencies failed to install!
        pause
        exit /b 1
    )
    echo [Setup] Verifying core imports...
    .venv\Scripts\python -c "import openai; import tenacity; import requests; import rich; import prompt_toolkit; print('Core imports OK')"
    if errorlevel 1 (
        echo [ERROR] Core import check failed! Try: .venv\Scripts\pip install -r requirements-core.txt
        pause
        exit /b 1
    )
    echo [Setup] Installing optional dependencies...
    .venv\Scripts\pip install -q -r requirements.txt 2>nul
    echo [Setup] Done.
)
echo.
echo Starting Orca Code (Local Mode)...
echo Make sure LM Studio / Ollama is running!
.venv\Scripts\python orca_code.py
pause
