@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Ultimate Agent Factory

where py >nul 2>&1
if errorlevel 1 goto try_python

py -3 -c "import sys; raise SystemExit(sys.version_info ^< (3, 11))" >nul 2>&1
if not errorlevel 1 goto use_py_latest

py -3.11 -c "import sys" >nul 2>&1
if not errorlevel 1 goto use_py_311

echo Compatible Python 3.11+ is not registered. Trying the Microsoft Python install manager...
py install 3.11
if errorlevel 1 goto python_failed
py -3.11 -c "import sys" >nul 2>&1
if errorlevel 1 goto python_failed
goto use_py_311

:use_py_latest
set "UAF_PYTHON=py -3"
goto launch

:use_py_311
set "UAF_PYTHON=py -3.11"
goto launch

:try_python
where python >nul 2>&1
if errorlevel 1 goto python_missing
python -c "import sys; raise SystemExit(sys.version_info ^< (3, 11))" >nul 2>&1
if errorlevel 1 goto python_missing
set "UAF_PYTHON=python"
goto launch

:python_missing
echo Python 3.11+ was not found. Install it from https://www.python.org/downloads/windows/
echo Then rerun this file. No API key is entered in this window.
goto failed

:python_failed
echo Automatic Python installation did not complete. Use https://www.python.org/downloads/windows/
echo or repair the Microsoft Python install manager, then rerun this file.
goto failed

:launch
%UAF_PYTHON% scripts\start_factory.py %*
set "UAF_EXIT=%ERRORLEVEL%"
if not "%UAF_EXIT%"=="0" goto failed_with_code
exit /b 0

:failed_with_code
echo.
echo UAF stopped with exit code %UAF_EXIT%. Read the recovery message above.
pause
exit /b %UAF_EXIT%

:failed
echo.
pause
exit /b 1
