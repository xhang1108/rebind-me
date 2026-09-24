@echo off
rem Remove the Rebind Me plugin from OpenCode 2 / OpenChamber 2. No elevation needed.
rem
rem Deletes the local copy in ~/.config/opencode/plugins/ and drops the
rem rebind-me entry from the OpenCode config. Reload OpenCode 2 / OpenChamber 2 after.
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "PYTHON="
for /f "delims=" %%P in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PYTHON=%%P"

if not defined PYTHON (
  echo [ERROR] Python 3.10+ was not found on PATH.
  exit /b 1
)

"%PYTHON%" "%SCRIPT_DIR%rebind-me.pyw" plugin uninstall
if errorlevel 1 (
  echo [ERROR] Plugin uninstall failed.
  exit /b 1
)

echo.
echo Reload OpenCode 2 / OpenChamber 2 to apply.
endlocal
