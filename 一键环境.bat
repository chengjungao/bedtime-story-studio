@echo off
rem ================================================================
rem  One-click environment  /  Windows
rem
rem  Double-click this file. It does exactly one of two things:
rem
rem    everything present  -> prints a summary and exits
rem    something missing   -> shows what, how much to download and
rem                           whether disk is enough, waits for Enter,
rem                           then installs only the missing steps
rem
rem  Nothing is installed silently, and re-running is safe: finished
rem  steps are skipped, unfinished downloads resume.
rem
rem  It will NOT install Python or ffmpeg for you - those touch the
rem  system. If ffmpeg is missing it prints the exact command instead.
rem
rem  NOTE: pure ASCII on purpose. Chinese inside a .bat gets garbled
rem  under the default 936 codepage, so every Chinese line is printed
rem  by Python (app.py --setup).
rem
rem  Arguments are passed straight through:
rem    --yes        do not ask, install right away
rem    --cpu        CPU build of PyTorch (no NVIDIA card)
rem    --no-mirror  download the model without a mirror
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
%PY% app.py --setup %*
set RC=%ERRORLEVEL%
popd
echo.
pause
endlocal
exit /b %RC%

:no_python
echo.
echo   Python was not found.
echo.
echo   Install Python 3.11 from https://www.python.org/downloads/
echo   and tick "Add python.exe to PATH" during setup, then run this file again.
echo.
pause
exit /b 1
