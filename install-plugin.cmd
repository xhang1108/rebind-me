@echo off
rem Install the Rebind Me plugin into opencode. No elevation needed.
rem
rem Uses npm when rebind-me is published, otherwise copies the plugin
rem from this checkout into ~/.config/opencode/plugins/. Restart opencode after.
rem The plugin only reports to the bridge, so run install.cmd first.
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "PYTHON="
for /f "delims=" %%P in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PYTHON=%%P"

if not defined PYTHON (
  echo [ERROR] Python 3.10+ was not found on PATH.
  exit /b 1
)

where opencode >nul 2>&1
if errorlevel 1 (
  echo [WARN] opencode was not found on PATH. Install it first:
  echo        npm install -g opencode-ai
  echo.
)

"%PYTHON%" "%SCRIPT_DIR%rebind-me.pyw" plugin install
if errorlevel 1 (
  echo [ERROR] Plugin install failed.
  exit /b 1
)

echo.
echo Restart opencode to load the plugin.
endlocal
