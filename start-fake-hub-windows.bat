@echo off
rem Start the stand-in hub (development only).
rem Usage: start-fake-hub-windows.bat [port] [/nopause]
setlocal
cd /d "%~dp0"

set "PORT="
set "NOPAUSE="
:args
if "%~1"=="" goto argsdone
if /i "%~1"=="/nopause" (set "NOPAUSE=1") else if /i "%~1"=="--no-pause" (set "NOPAUSE=1") else if not defined PORT (set "PORT=%~1")
shift
goto args
:argsdone
if not defined PORT set "PORT=8631"

call :findpython
if not defined PY goto nopython

echo Starting the stand-in hub on port %PORT%. Press Ctrl-C to stop.
%PY% fake-partner-hub.py --port %PORT%
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
