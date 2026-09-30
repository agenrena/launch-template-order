@echo off
rem Start this store's App on this computer (double-click, or run start.bat).
rem Needs uv (https://docs.astral.sh/uv/) and Node.js 22.12+. Data stays in data\.
chcp 65001 >nul
cd /d "%~dp0"
where uv >nul 2>nul || (echo 需要先安裝 uv（可以請你的 Agent 安裝）：https://docs.astral.sh/uv/ & pause & exit /b 1)
uv run --no-project --python 3.13 --with-requirements backend\requirements.txt python scripts\start.py %*
if errorlevel 1 pause
