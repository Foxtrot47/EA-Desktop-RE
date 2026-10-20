@echo off
setlocal
cd /d "%~dp0"
where pyw.exe >nul 2>nul
if %errorlevel%==0 (
  start "EA Custom Launcher" pyw.exe -3 gui.py
) else (
  start "EA Custom Launcher" pythonw.exe gui.py
)
endlocal
