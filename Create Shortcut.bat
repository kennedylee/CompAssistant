@echo off
echo Creating CompAssistant desktop shortcut...

powershell -ExecutionPolicy Bypass -Command ^
  "$s = (New-Object -COM WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop') + '\CompAssistant.lnk');" ^
  "$s.TargetPath = '%~dp0CompAssistant.exe';" ^
  "$s.WorkingDirectory = '%~dp0';" ^
  "$s.IconLocation = '%~dp0CompAssistant.exe,0';" ^
  "$s.Description = 'AI Desktop Assistant';" ^
  "$s.Save()"

echo.
echo Done! CompAssistant shortcut added to your desktop.
pause
