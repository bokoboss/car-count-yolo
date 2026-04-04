@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo Vehicle Counter - Windows Setup
echo ==========================================
echo.

if exist ".venv\Scripts\python.exe" goto venv_ready

echo [1/3] Creating virtual environment...
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m venv .venv
) else (
    python -m venv .venv
)
if errorlevel 1 goto setup_failed

:venv_ready
echo [2/3] Activating virtual environment...
call ".venv\Scripts\activate.bat"
if errorlevel 1 goto setup_failed

echo [3/3] Installing required packages...
python -m pip install --upgrade pip
if errorlevel 1 goto setup_failed
python -m pip install -r requirements.txt
if errorlevel 1 goto setup_failed

echo.
echo Setup completed successfully.
echo Next time, you can start the app by double-clicking run_app.bat
echo.
pause
exit /b 0

:setup_failed
echo.
echo Setup failed.
echo Please check that Python is installed, then run this file again.
echo If Python is not installed yet, download it from https://www.python.org/downloads/windows/
echo.
pause
exit /b 1
