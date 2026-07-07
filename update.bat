@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Orca Code - 更新

echo ======================================
echo   Orca Code - 检查更新
echo ======================================
echo.

:: ---- Step 1: Check git ----
echo [1/3] 检查 Git...
where git >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 Git。
    echo 请从 https://git-scm.com 安装 Git 后重试。
    pause
    exit /b 1
)
for /f "tokens=1" %%v in ('git --version') do echo   %%v 已安装

:: ---- Step 2: Check remote connectivity ----
echo [2/3] 检查远程仓库...
git fetch origin --quiet 2>nul
if errorlevel 1 (
    echo [ERROR] 无法连接到 GitHub。
    echo 请检查网络连接和代理设置。
    echo.
    echo 如果使用了代理，请运行：
    echo   git config --global http.proxy http://127.0.0.1:端口
    echo   git config --global https.proxy http://127.0.0.1:端口
    pause
    exit /b 1
)
echo   远程仓库连接正常

:: ---- Step 3: Compare and pull ----
echo [3/3] 检查本地与远程差异...

:: Get local and remote HEAD
for /f %%v in ('git rev-parse HEAD') do set LOCAL=%%v
for /f %%v in ('git rev-parse origin/main') do set REMOTE=%%v

if "!LOCAL!"=="!REMOTE!" (
    echo   本地已是最新版本 ^(!LOCAL:~0,8!^)
    echo.
    echo ======================================
    echo   无需更新
    echo ======================================
    timeout /t 3 >nul
    exit /b 0
)

:: Show what's new
echo   发现新版本：
echo     本地: !LOCAL:~0,8!
echo     远程: !REMOTE:~0,8!
echo.
echo   远程更新日志：
git log !LOCAL!..origin/main --oneline --no-decorate 2>nul
echo.

:: Stash any local changes before pulling
git stash --include-untracked --quiet 2>nul
set STASHED=0
if not errorlevel 1 (
    git stash list | findstr "stash" >nul && set STASHED=1
)

:: Pull
echo   正在拉取更新...
git pull origin main --ff-only --quiet 2>nul
if errorlevel 1 (
    echo [ERROR] 拉取失败，可能是本地有未提交的修改。
    echo   尝试强制更新...
    git fetch origin --quiet
    git reset --hard origin/main --quiet
    if errorlevel 1 (
        echo [ERROR] 更新失败，请手动处理。
        pause
        exit /b 1
    )
)

:: Restore stashed changes
if !STASHED! equ 1 (
    echo   恢复本地修改...
    git stash pop --quiet 2>nul
)

echo.
echo ======================================
echo   更新完成
echo ======================================
echo.
echo   已更新到 !REMOTE:~0,8!
echo   请重新运行 start.bat 启动。
echo.
echo   如果遇到依赖变化，可能需要重新安装：
echo     .venv\Scripts\pip install -e .
echo.
echo   按任意键退出...
pause >nul
