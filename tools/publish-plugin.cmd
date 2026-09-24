@echo off
rem Maintainer release: publish the OpenCode 2 plugin to npm.
rem
rem Bump "version" in plugin\package.json (0.2.0 for the V2 migration) first, then run this with an npm
rem account that owns the name (`npm login`, or an .npmrc token).
setlocal EnableExtensions

pushd "%~dp0..\plugin" || exit /b 1
call npm publish
set "CODE=%ERRORLEVEL%"
popd

exit /b %CODE%
