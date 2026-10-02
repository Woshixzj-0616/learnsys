@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=D:\Desktop\bilinote\asr-venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=D:\python\pythonw.exe"
start "" "%PY%" main.py