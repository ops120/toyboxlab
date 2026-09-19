@echo off
chcp 65001 >nul
cd /d "%~dp0"
if "%~1"=="" (
    echo 用法：把要删除的文件拖到本文件上
    pause
    exit /b
)
python "%~dp0delete_monster.py" "%~1"
