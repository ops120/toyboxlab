@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m PyInstaller --onefile --windowed --noconsole --clean ^
  --name "花屏模拟器" ^
  main.py
echo.
echo 产物: dist\花屏模拟器.exe
pause
