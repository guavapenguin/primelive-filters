@echo off
cd /d "%~dp0"
echo primelive 一鍵濾鏡（順暢模式 540p）啟動中...
".venv\Scripts\python.exe" primelive_engine.py --fast %*
if errorlevel 1 pause
