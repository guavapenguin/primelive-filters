@echo off
cd /d "%~dp0"
echo primelive 一鍵濾鏡（手機鏡頭模式）啟動中...
echo.
echo 使用前：手機需先透過「連結至 Windows / 連線相機」連上電腦，
echo         啟動後手機會跳出「允許電腦使用相機」，請在手機上按同意。
echo.
".venv\Scripts\python.exe" primelive_engine.py --camera-name "虛擬攝影機" --allow-phone %*
if errorlevel 1 pause
