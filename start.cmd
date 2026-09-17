@echo off
REM Elysia launcher - Windows double-click wrapper.
REM Usage: start.cmd [--no-model] [--no-agent] [--no-hud] [--host H] [--port P]
REM        start.cmd stop | status | restart | doctor
REM Prefer start.ps1 for the full flag set; this forwards the same arguments.

setlocal
set "ROOT=%~dp0"

REM Prefer the py launcher: the Windows Store python.exe stub also matches
REM `where python` but does not actually run Python.
set "PY="
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo [elysia] Python 3.8+ is required but was not found on PATH.
  echo          Install it with:  winget install -e --id Python.Python.3.12
  exit /b 1
)

REM A leading verb selects the action; a leading flag keeps the default (start).
set "VERB=start"
set "ARGS=%*"
if /I "%~1"=="start"   set "VERB=start"   & set "ARGS="
if /I "%~1"=="stop"    set "VERB=stop"    & set "ARGS="
if /I "%~1"=="restart" set "VERB=restart" & set "ARGS="
if /I "%~1"=="status"  set "VERB=status"  & set "ARGS="
if /I "%~1"=="doctor"  set "VERB=doctor"  & set "ARGS="
if /I "%~1"=="install" set "VERB=install" & set "ARGS="

%PY% "%ROOT%scripts\elysia_boot.py" %VERB% %ARGS%
exit /b %ERRORLEVEL%
