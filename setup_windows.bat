@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (
  py install.py %*
  exit /b %errorlevel%
)
where python >nul 2>&1
if %errorlevel%==0 (
  python install.py %*
  exit /b %errorlevel%
)
echo [Live Server] Python 3.11+ was not found.
echo Install Python, then run setup_windows.bat again.
exit /b 1
