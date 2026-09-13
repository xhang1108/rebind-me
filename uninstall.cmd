@echo off
rem One-time elevated uninstall for Rebind Me.
rem Right-click this file and choose "Run as administrator".
rem
rem Removes the bridge scheduled task and the tray HKCU Run entry. Runtime data
rem in %LOCALAPPDATA%\RebindMe\ is kept unless you pass "purge".
setlocal EnableExtensions

set "TASK_NAME=RebindMe-Bridge"
set "RUN_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
set "RUN_VALUE=RebindMe-Tray"
set "DATA_DIR=%LOCALAPPDATA%\RebindMe"
set "PURGE=%~1"

net session >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Administrator privileges are required.
  echo         Right-click uninstall.cmd and choose "Run as administrator".
  exit /b 1
)

rem --- stop and delete the bridge task ---
schtasks /End /TN "%TASK_NAME%" >nul 2>&1
schtasks /Delete /TN "%TASK_NAME%" /F >nul 2>&1

rem --- remove the tray logon entry ---
reg delete "%RUN_KEY%" /V "%RUN_VALUE%" /F >nul 2>&1

if /I "%PURGE%"=="purge" (
  if exist "%DATA_DIR%" rd /s /q "%DATA_DIR%"
  echo Removed runtime data at "%DATA_DIR%".
)

echo Rebind Me uninstalled.
endlocal
