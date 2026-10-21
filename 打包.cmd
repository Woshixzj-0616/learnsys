@echo off
chcp 936 >nul
cd /d "%~dp0"
echo 正在把「学习工作台」打包成 exe，第一次要一分钟左右…
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean 学习工作台.spec
if errorlevel 1 (
  echo.
  echo 打包失败：把上面的红色报错发我。
  pause
  exit /b 1
)
echo.
echo 打包好了：%~dp0dist\学习工作台\学习工作台.exe
echo 整个 dist\学习工作台\ 文件夹一起拷走就能用。
pause
exit /b 0
