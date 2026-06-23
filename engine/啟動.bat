@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo primelive 一鍵濾鏡引擎 啟動中...
".venv\Scripts\python.exe" primelive_engine.py %*
if errorlevel 1 pause
