@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python Launcher was not found. Install Python 3.12 and try again.
  exit /b 1
)

if not exist ".build-venv\Scripts\python.exe" (
  py -3.12 -m venv .build-venv
  if errorlevel 1 goto build_failed
)

".build-venv\Scripts\python.exe" -m pip install -r requirements-desktop.txt
if errorlevel 1 goto build_failed

".build-venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name UpLateMusic --add-data "index.html;." --collect-all webview --collect-all clr_loader --collect-all pythonnet desktop_app.py
if errorlevel 1 goto build_failed

echo.
echo Build complete: dist\UpLateMusic.exe
exit /b 0

:build_failed
echo.
echo The desktop app build failed. Review the error above and try again.
exit /b 1
