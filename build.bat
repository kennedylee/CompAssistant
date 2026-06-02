@echo off
echo ==========================================
echo   CompAssistant Build
echo ==========================================
echo.

call venv\Scripts\activate.bat

echo Installing PyInstaller...
pip install pyinstaller --quiet

echo.
echo Building application (this takes 1-2 minutes)...
pyinstaller CompAssistant.spec --noconfirm --clean

if %errorlevel% neq 0 (
    echo.
    echo BUILD FAILED. See errors above.
    pause
    exit /b 1
)

echo.
echo Copying extra files...
copy /Y "Create Shortcut.bat" "dist\CompAssistant\Create Shortcut.bat"

echo.
echo Creating zip...
if exist CompAssistant_release.zip del CompAssistant_release.zip
powershell -Command "Compress-Archive -Path 'dist\CompAssistant\*' -DestinationPath 'CompAssistant_release.zip'"

echo.
echo ==========================================
echo   Done!
echo   File: CompAssistant_release.zip
echo   Share this zip with your friend.
echo   They unzip it and double-click CompAssistant.exe
echo ==========================================
pause
