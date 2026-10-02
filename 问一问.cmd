@echo off
chcp 936 >nul
cd /d "%~dp0"
rem 有打包好的「问一问.exe」就用它：没黑框，任务栏固定出来就叫「问一问」
set "EXE=%~dp0dist\问一问\问一问.exe"
if exist "%EXE%" (
  start "" "%EXE%"
  exit /b 0
)
rem 还没打包才退回源码跑（相当于 问一问-调试.cmd 的无黑框版）
set "PY=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=D:\Desktop\bilinote\asr-venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=D:\python\pythonw.exe"
start "" "%PY%" -m learnsys.ask.app