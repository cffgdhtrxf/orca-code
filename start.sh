#!/bin/bash
cd "$(dirname "$0")"
if [ ! -f ".venv/bin/python" ]; then
    echo "[Setup] Creating virtual environment..."
    python3 -m venv .venv
    echo "[Setup] Installing dependencies..."
    .venv/bin/pip install -q -r requirements.txt
    echo "[Setup] Done."
fi
echo
echo "Starting Orca Code..."
.venv/bin/python orca_code.py
