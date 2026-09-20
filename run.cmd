@echo off
rem Manual start for Rebind Me.
rem
rem Starts the tray (normal privileges) and, if it is installed, the elevated
rem bridge scheduled task. Run install.cmd as administrator once to create that
rem task; without it, run the bridge yourself in an elevated terminal with
rem `python -m rebind_me`. Open the UI from the tray icon or at
rem http://127.0.0.1:4173/.
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "TASK_NAME=RebindMe-Bridge"
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

rem --- start the elevated bridge if the scheduled task exists ---
schtasks /Query /TN "%TASK_NAME%" >nul 2>&1
if errorlevel 1 (
  echo [INFO] Bridge task "%TASK_NAME%" is not installed.
  echo        Run install.cmd as administrator once for the elevated bridge,
  echo        or start it manually with:  python -m rebind_me
) else (
  schtasks /Run /TN "%TASK_NAME%" >nul 2>&1
)

rem --- tray (owns the icon and the UI entry point) ---
start "" "%PYTHONW%" "%SCRIPT_DIR%rebind-me.pyw" tray
endlocal
