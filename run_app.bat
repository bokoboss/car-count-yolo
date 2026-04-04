@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment was not found.
    echo Please run setup_windows.bat first.
    echo.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo Could not activate the virtual environment.
    echo Please run setup_windows.bat again.
    echo.
    pause
    exit /b 1
)

python -m src.vehicle_counter
set "APP_EXIT=%errorlevel%"

if not "%APP_EXIT%"=="0" (
    echo.
    echo The app closed with an error code: %APP_EXIT%
    echo If needed, run setup_windows.bat again to reinstall dependencies.
    echo.
    pause
)

exit /b %APP_EXIT%
