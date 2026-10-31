@echo off
setlocal
cd /d "%~dp0"
set "attempts=0"
curl.exe --silent --fail http://127.0.0.1:8000/ >nul 2>nul
if not errorlevel 1 goto open_app
where py >nul 2>nul
if errorlevel 1 goto start_python
start "Up late Music server" /min cmd /k py -3 server.py
goto wait_for_server

:start_python
start "Up late Music server" /min cmd /k python server.py

:wait_for_server
set /a attempts+=1
curl.exe --silent --fail http://127.0.0.1:8000/ >nul 2>nul
if not errorlevel 1 goto open_app
if %attempts% geq 20 goto server_failed
timeout /t 1 /nobreak >nul
goto wait_for_server

:open_app
start "" "http://127.0.0.1:8000"
exit /b 0

:server_failed
echo The Up late Music server did not start. Check that Python is installed and port 8000 is available.
pause
exit /b 1
