@echo off
rem ================================================================
rem  Bedtime Story in Your Own Voice  /  Windows launcher
rem
rem  Double-click this file. It opens a menu:
rem    0  install environment (first run, downloads about 8 GB)
rem    1  narrate     2  mix     3  verify     4  all three
rem    5  trial: first 3 paragraphs only
rem    6  check      7  change project folder
rem
rem  NOTE: this file is deliberately pure ASCII. Chinese text inside a
rem  .bat gets garbled under the default 936 codepage, so every Chinese
rem  message is printed by Python instead (see app.py).
rem
rem  Arguments are passed straight through to app.py:
rem    --check        only report what is missing
rem    --install      install only
rem    --all          narrate + mix + verify
rem    --project DIR  use another project folder
rem ================================================================

chcp 65001 >nul
setlocal

rem Prefer 3.10 / 3.11 / 3.12: PyTorch 2.4.0 ships wheels for those.
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
%PY% app.py %*
set RC=%ERRORLEVEL%
popd
goto done

:no_python
echo.
echo   Python was not found.
echo.
echo   Install Python 3.11 from https://www.python.org/downloads/
echo   and tick "Add python.exe to PATH" during setup, then run this file again.
echo.
echo   Already have Python? Run "python app.py" in a terminal to see the error.
echo.
set RC=1
goto done

:done
if not "%RC%"=="0" pause
endlocal
exit /b %RC%
