@echo off
setlocal
cd /d "%~dp0"
if exist "dist\ChatBridge-2.50.0.exe" (
  start "ChatBridge 2.60.0" /wait "dist\ChatBridge-2.50.0.exe"
  exit /b %errorlevel%
)
if exist "ChatBridge-2.50.0.exe" (
  start "ChatBridge 2.60.0" /wait "ChatBridge-2.50.0.exe"
  exit /b %errorlevel%
)
echo ChatBridge-2.50.0.exe was not found.
echo Run build_exe.bat once on Windows x64, then double-click this file.
pause
exit /b 1
