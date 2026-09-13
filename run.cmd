@echo off
rem Launch Rebind Me manually with normal privileges (tray + bridge control).
rem For the elevated bridge, use the scheduled task instead (see install.cmd).
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "PYTHONW="
for /f "delims=" %%P in ('python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') do set "PYTHONW=%%P"

if not defined PYTHONW (
  echo [ERROR] Python 3.10+ was not found on PATH.
  exit /b 1
)
if not exist "%PYTHONW%" (
  echo [ERROR] pythonw.exe not found at "%PYTHONW%".
  exit /b 1
)

start "" "%PYTHONW%" "%SCRIPT_DIR%rebind-me.pyw" tray
endlocal
