@echo off
rem One-time elevated install for Rebind Me.
rem Right-click this file and choose "Run as administrator".
rem
rem It registers the elevated bridge scheduled task (runs at logon, highest
rem privileges), writes the tray HKCU Run entry, and starts the bridge now.
rem Start/stop after this is handled by the tray; no further UAC prompts.
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "TASK_NAME=RebindMe-Bridge"
set "RUN_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
set "RUN_VALUE=RebindMe-Tray"
set "LAUNCHER=%SCRIPT_DIR%rebind-me.pyw"

rem --- require elevation ---
net session >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Administrator privileges are required.
  echo         Right-click install.cmd and choose "Run as administrator".
  exit /b 1
)

rem --- resolve pythonw.exe from the active Python interpreter ---
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

rem --- bridge: elevated scheduled task, trigger at logon ---
rem TODO(stage 5): import task XML to also set MultipleInstances=IgnoreNew and
rem RestartOnFailure=1min x3, which the schtasks command line cannot express.
schtasks /Create /TN "%TASK_NAME%" /TR "\"%PYTHONW%\" \"%LAUNCHER%\" bridge" /SC ONLOGON /RL HIGHEST /F
if errorlevel 1 (
  echo [ERROR] Failed to create scheduled task "%TASK_NAME%".
  exit /b 1
)

rem --- tray: HKCU Run entry, normal privileges ---
reg add "%RUN_KEY%" /V "%RUN_VALUE%" /T REG_SZ /D "\"%PYTHONW%\" \"%LAUNCHER%\" tray" /F
if errorlevel 1 (
  echo [ERROR] Failed to register the tray at logon.
  exit /b 1
)

rem --- start the bridge now, without a UAC prompt ---
schtasks /Run /TN "%TASK_NAME%"

echo.
echo Rebind Me installed.
echo   Bridge task : %TASK_NAME%  (elevated, at logon)
echo   Tray entry  : %RUN_VALUE%  (HKCU\...\Run)
echo   Python      : %PYTHONW%
echo.
echo Re-run this script after changing or reinstalling Python.
endlocal
