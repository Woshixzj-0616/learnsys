@echo off
chcp 936 >nul
cd /d "%~dp0"
rem 优先启动打包好的 学习工作台.exe；源码模式用 pythonw 跑（等价于 学习工作台-调试.cmd，无黑框）
set "EXE=%~dp0dist\学习工作台\学习工作台.exe"
if exist "%EXE%" (
  start "" "%EXE%" %*
  exit /b 0
)
set "PY=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=D:\Desktop\bilinote\asr-venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=D:\python\pythonw.exe"
start "" "%PY%" -m learnsys.ask.app %*
