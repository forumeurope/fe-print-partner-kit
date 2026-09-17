@echo off
rem Start the example print client.
rem Usage: start-client-windows.bat [hub address] [hub port] [/nopause]
setlocal
cd /d "%~dp0"

set "HUB="
set "PORT="
set "NOPAUSE="
:args
if "%~1"=="" goto argsdone
if /i "%~1"=="/nopause" (set "NOPAUSE=1") else if /i "%~1"=="--no-pause" (set "NOPAUSE=1") else if not defined HUB (set "HUB=%~1") else if not defined PORT (set "PORT=%~1")
shift
goto args
:argsdone
if not defined PORT set "PORT=8631"

call :findpython
if not defined PY goto nopython

if not defined HUB set /p "HUB=Hub address [127.0.0.1]: "
if not defined HUB set "HUB=127.0.0.1"

echo Collecting badges from %HUB%:%PORT% into %CD%\badges. Press Ctrl-C to stop.
%PY% print-partner-client.py --hub %HUB% --port %PORT% --out badges
goto end

:findpython
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3" && goto :eof
python --version >nul 2>&1 && set "PY=python"
goto :eof

:nopython
echo Python 3 was not found.
echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".

:end
if not defined NOPAUSE pause
endlocal
