@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=D:\Desktop\bilinote\asr-venv\Scripts\python.exe"
if not exist "%PY%" set "PY=D:\python\python.exe"
"%PY%" -m learnsys.ask.app
pause
