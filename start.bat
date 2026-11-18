@echo off
setlocal
cd /d "%~dp0"

rem Find Python: 1) project .venv, 2) envs\default, 3) system PATH
set PY=

if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

if not defined PY (
    if exist "%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe" (
        set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
    )
)

if not defined PY (
    where python >nul 2>nul && set PY=python
)

if not defined PY (
    echo [ERROR] Python not found. Please install Python 3.10+.
    pause
    exit /b 1
)

echo ============================================
echo  品牌A QC System 4.0
echo  Python: %PY%
echo ============================================
echo Starting... if no window pops up, wait a few seconds.
"%PY%" app.py
echo.
echo Program exited with code %errorlevel%
pause
