@echo off
rem ================================================================
rem  Check only: reports what is installed, what is missing,
rem  and how much disk the model takes. Installs nothing.
rem
rem  Pure ASCII on purpose - Chinese comes from Python.
rem ================================================================

chcp 65001 >nul
setlocal

set "PY="
for %%V in (3.12 3.11 3.10) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
  )
)
if not defined PY (
  py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)

if not defined PY goto no_python

pushd "%~dp0"
%PY% app.py --check
set RC=%ERRORLEVEL%
popd
pause
endlocal
exit /b %RC%

:no_python
echo.
echo   Python was not found. Install Python 3.11 first.
echo.
pause
exit /b 1
