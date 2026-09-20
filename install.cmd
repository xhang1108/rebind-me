@echo off
rem One-time elevated install for Rebind Me.
rem Right-click this file and choose "Run as administrator".
rem
rem It registers the elevated bridge scheduled task (runs at startup, highest
rem privileges, ignore-new + restart-on-failure) and the tray HKCU Run entry,
rem then starts the bridge now. Start/stop after this is handled by the tray;
rem no further UAC prompts. The task itself is generated as Task Scheduler XML
rem by Python (schtasks cannot express MultipleInstances or RestartOnFailure).
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "TASK_NAME=RebindMe-Bridge"
set "LAUNCHER=%SCRIPT_DIR%rebind-me.pyw"

rem --- require elevation ---
net session >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Administrator privileges are required.
  echo         Right-click install.cmd and choose "Run as administrator".
  exit /b 1
)

rem --- resolve python.exe / pythonw.exe from the active interpreter ---
set "PYTHON="
set "PYTHONW="
for /f "delims=" %%P in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PYTHON=%%P"
for /f "delims=" %%P in ('python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') do set "PYTHONW=%%P"

if not defined PYTHON (
  echo [ERROR] Python 3.10+ was not found on PATH.
  exit /b 1
)
if not exist "%PYTHONW%" (
  echo [ERROR] pythonw.exe not found at "%PYTHONW%".
  exit /b 1
)
if not exist "%LAUNCHER%" (
  echo [ERROR] Launcher not found at "%LAUNCHER%".
  exit /b 1
)

rem --- bridge task + tray Run entry (via the frozen autostart helper) ---
"%PYTHON%" "%LAUNCHER%" autostart enable
if errorlevel 1 (
  echo [ERROR] Failed to register autostart.
  exit /b 1
)

rem --- start the bridge now, without a UAC prompt ---
schtasks /Run /TN "%TASK_NAME%"

echo.
echo Rebind Me installed.
echo   Bridge task : %TASK_NAME%  (elevated, at startup)
echo   Tray entry  : RebindMe-Tray  (HKCU\...\Run)
echo   Python      : %PYTHONW%
echo.
echo Re-run this script after changing or reinstalling Python.
endlocal
