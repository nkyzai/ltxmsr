@echo off
title LTX-MSR CineAgent Producer

:: 1. Navigate to the script directory (ensures it works from anywhere)
cd /d "%~dp0"

:: 2. Check if virtual environment exists
if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found!
    echo Please run: python -m venv venv
    echo Then run: pip install -r requirements.txt
    pause
    exit /b 1
)

:: 3. Activate the virtual environment
echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat

:: 4. Run the GUI application
echo [INFO] Starting CineAgent GUI...
python gui_app.py

:: 5. If the app crashes or closes, keep the window open to see errors
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Application exited with error code %errorlevel%
    pause
)