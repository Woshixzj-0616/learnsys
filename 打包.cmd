@echo off
chcp 936 >nul
cd /d "%~dp0"
echo 正在把「问一问」打包成 exe ……（第一次要一两分钟）
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean 问一问.spec
if errorlevel 1 (
  echo.
  echo 打包失败了 —— 把上面的红字发我。
  pause
  exit /b 1
)
echo.
echo 打好了：%~dp0dist\问一问\问一问.exe
echo （整个 dist\问一问\ 文件夹一起拷走就能用）
pause
exit /b 0