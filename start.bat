@echo off
chcp 65001 > nul
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel% neq 0 (
    where py >nul 2>nul
    if %errorlevel% neq 0 (
        echo.
        echo ❌ 没找到 Python。请先去 https://www.python.org/downloads/ 装一个 Python 3.9+
        echo    安装时记得勾上 "Add Python to PATH"
        echo.
        pause
        exit /b 1
    )
    py start.py
) else (
    python start.py
)

pause
