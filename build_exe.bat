@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto :error
)
".venv\Scripts\python.exe" -c "import platform,struct,sys; sys.exit(0 if platform.system()=='Windows' and struct.calcsize('P')==8 and platform.machine().upper() in ('AMD64','X86_64') else 1)"
if errorlevel 1 (
  echo Build requires Windows with x64 Python.
  goto :error
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt "pyinstaller>=6.10,<7"
if errorlevel 1 goto :error
".venv\Scripts\python.exe" scripts\ver_check.py
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm ChatBridge.spec
if errorlevel 1 goto :error
if not exist "dist\ChatBridge-2.50.0.exe" goto :error
echo Built dist\ChatBridge-2.50.0.exe
exit /b 0
:error
echo Build failed. See the error above.
exit /b 1
