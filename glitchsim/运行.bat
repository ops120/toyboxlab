@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "dist\花屏模拟器.exe" (
  start "" "dist\花屏模拟器.exe"
  exit /b
)
set "PYW=C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
if exist "%PYW%" (
  start "" "%PYW%" main.py
  exit /b
)
start "" pythonw main.py
