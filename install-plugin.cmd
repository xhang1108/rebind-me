@echo off
rem Install the Rebind Me plugin into OpenCode 2 / OpenChamber 2. No elevation needed.
rem
rem Uses npm when a V2-compatible rebind-me release is published, otherwise copies the plugin
rem from this checkout into ~/.config/opencode/plugins/. Reload OpenCode 2
rem or OpenChamber 2 after installation. The plugin only reports to the
rem bridge, so run install.cmd first.
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PYTHON="
for /f "delims=" %%P in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PYTHON=%%P"

if not defined PYTHON (
  echo [ERROR] Python 3.10+ was not found on PATH.
  exit /b 1
)

rem Prefer OpenChamber's bundled runtime. The PATH command can still be an
rem unrelated OpenCode 1.x installation, which must not block OpenChamber 2.
set "OPENCODE_BIN="
set "OPENCODE_VERSION="
set "OPENCODE_MAJOR="
set "OPENCODE_MINOR="
set "OPENCODE_PATCH="
set "OPENCODE_UNSUPPORTED="
set "OPENCODE_SOURCE=standalone"
if exist "%LOCALAPPDATA%\Programs\@openchamberelectron\resources\opencode-cli\opencode.exe" (
  set "OPENCODE_BIN=%LOCALAPPDATA%\Programs\@openchamberelectron\resources\opencode-cli\opencode.exe"
  set "OPENCODE_SOURCE=OpenChamber managed"
)
if not defined OPENCODE_BIN (
  for /f "delims=" %%P in ('where opencode.exe 2^>nul') do if not defined OPENCODE_BIN set "OPENCODE_BIN=%%P"
)
if not defined OPENCODE_BIN (
  for /f "delims=" %%P in ('where opencode.cmd 2^>nul') do if not defined OPENCODE_BIN set "OPENCODE_BIN=%%P"
)
if not defined OPENCODE_BIN (
  for /f "delims=" %%P in ('where opencode 2^>nul') do if not defined OPENCODE_BIN set "OPENCODE_BIN=%%P"
)

if defined OPENCODE_BIN (
  for /f "delims=" %%V in ('call "!OPENCODE_BIN!" --version 2^>nul') do if not defined OPENCODE_VERSION set "OPENCODE_VERSION=%%V"
  if defined OPENCODE_VERSION (
    rem OpenCode 2 prints `opencode v2.0.15`; older CLI builds print only
    rem the numeric version. Normalize both forms before checking 2.0.15+.
    for /f "tokens=1,2" %%A in ("!OPENCODE_VERSION!") do (
      if /I "%%A"=="opencode" (
        set "OPENCODE_VERSION=%%B"
      ) else (
        set "OPENCODE_VERSION=%%A"
      )
    )
    set "OPENCODE_VERSION=!OPENCODE_VERSION:v=!"
    for /f "tokens=1,2,3 delims=." %%A in ("!OPENCODE_VERSION!") do (
      set "OPENCODE_MAJOR=%%A"
      set "OPENCODE_MINOR=%%B"
      set "OPENCODE_PATCH=%%C"
    )
    if defined OPENCODE_PATCH for /f "tokens=1 delims=-+" %%P in ("!OPENCODE_PATCH!") do set "OPENCODE_PATCH=%%P"
    set "OPENCODE_UNSUPPORTED="
    if not defined OPENCODE_MAJOR set "OPENCODE_UNSUPPORTED=1"
    if defined OPENCODE_MAJOR if !OPENCODE_MAJOR! LSS 2 set "OPENCODE_UNSUPPORTED=1"
    if defined OPENCODE_MAJOR if !OPENCODE_MAJOR! EQU 2 if !OPENCODE_MINOR! EQU 0 if !OPENCODE_PATCH! LSS 15 set "OPENCODE_UNSUPPORTED=1"
    if defined OPENCODE_UNSUPPORTED goto opencode_version_error
    echo !OPENCODE_SOURCE! OpenCode version: !OPENCODE_VERSION!
  ) else (
    echo [WARN] Could not read the OpenCode version from !OPENCODE_BIN!.
  )
) else (
  echo [WARN] opencode was not found on PATH. OpenChamber may use its managed binary.
)

if defined OPENCODE_UNSUPPORTED goto opencode_version_error
goto install_plugin

:opencode_version_error
echo [ERROR] OpenCode 2.0.15 or newer is required. Detected: !OPENCODE_VERSION!
echo         Upgrade OpenCode or use the OpenChamber managed runtime.
exit /b 1

:install_plugin
"%PYTHON%" "%SCRIPT_DIR%rebind-me.pyw" plugin install
if errorlevel 1 (
  echo [ERROR] Plugin install failed.
  exit /b 1
)

echo.
echo Reload OpenCode 2 / OpenChamber 2 to load the plugin.
endlocal
