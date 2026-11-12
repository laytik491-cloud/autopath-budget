@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 goto check_python
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if errorlevel 1 goto check_python
py -3 launch.py
goto finished
:check_python
where python >nul 2>&1
if errorlevel 1 goto missing
python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if errorlevel 1 goto missing
python launch.py
goto finished
:missing
echo Установите Python 3.11 или новее с сайта https://www.python.org/downloads/
echo Затем снова откройте этот файл.
:finished
pause
