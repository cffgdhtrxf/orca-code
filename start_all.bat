@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0orca-ts"
title Orca Code v5.3
echo Starting Orca Code...
echo TypeScript will auto-start Python backend.
echo.
call bun run dev
pause
