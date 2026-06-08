@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [Setup] Creating virtual environment...
    python -m venv .venv
    echo [Setup] Installing dependencies...
    .venv\Scripts\pip install -q -r requirements.txt
    echo [Setup] Done.
)
echo.
echo Starting Orca Code (Local Mode)...
echo Make sure LM Studio / Ollama is running!
.venv\Scripts\python orca_code.py
pause
