@echo off
echo ==========================================
echo   CompAssistant Setup
echo ==========================================
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Install Python 3.10+ from python.org
    pause
    exit /b 1
)

echo Creating virtual environment...
python -m venv venv

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Installing dependencies...
pip install --upgrade pip
pip install -r requirements.txt

echo.
echo ==========================================
echo   Setup complete!
echo   Run 'run.bat' to start CompAssistant
echo ==========================================
pause
