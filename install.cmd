@echo off
REM Elysia installer - Windows double-click wrapper.
REM Usage: install.cmd [--deps] [--build] [--with-model] [--dry-run]
REM Prefer install.ps1 for the full flag set; this forwards the same arguments.

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
  echo          ^(or https://www.python.org/downloads/ - tick "Add python.exe to PATH"^)
  pause
  exit /b 1
)

%PY% "%ROOT%scripts\elysia_boot.py" install %*
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
