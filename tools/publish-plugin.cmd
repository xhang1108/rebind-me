@echo off
rem Maintainer release: publish the opencode plugin to npm.
rem
rem Bump "version" in plugin\package.json first, then run this with an npm
rem account that owns the name (`npm login`, or an .npmrc token).
setlocal EnableExtensions

pushd "%~dp0..\plugin" || exit /b 1
call npm publish
set "CODE=%ERRORLEVEL%"
popd

exit /b %CODE%
