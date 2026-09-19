@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m PyInstaller --onefile --windowed --noconsole --clean --name "怪兽删除" delete_monster.py
echo.
echo 产物：dist\怪兽删除.exe
echo 用法：把要删除的文件拖到 exe 上
pause
