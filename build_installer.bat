@echo off
setlocal
cd /d "%~dp0"
set APP_VERSION=2.60.0
call build_exe.bat
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" scripts\sync_installer_version.py
if errorlevel 1 exit /b 1
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo Install Inno Setup 6 from https://jrsoftware.org/isinfo.php
  exit /b 1
)
"%ISCC%" ChatBridge.iss
if errorlevel 1 exit /b 1
if not exist "installer-output\ChatBridge-Setup-%APP_VERSION%.exe" exit /b 1
echo Built installer-output\ChatBridge-Setup-%APP_VERSION%.exe
exit /b 0
