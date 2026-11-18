@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem Build a portable Windows folder: dist\全量自动化客服质检系统\
rem Requires Python 3.10+ with: pip install -r requirements.txt pyinstaller

set PY=
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    if exist "%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe" (
        set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
    )
)
if not defined PY set "PY=python"

echo [BUILD] Using: %PY%
"%PY%" -m PyInstaller --noconfirm --clean --console --name "全量自动化客服质检系统" --paths src --collect-submodules qc_engine --exclude-module tkinter app.py
if errorlevel 1 (
    echo [BUILD] FAILED
    pause
    exit /b 1
)

echo [COPY] config / docs / data
xcopy /E /I /Y config "dist\全量自动化客服质检系统\config" >nul
if exist "dist\全量自动化客服质检系统\config\ai_config.json" del "dist\全量自动化客服质检系统\config\ai_config.json"
if exist "config\ai_config.example.json" copy /Y "config\ai_config.example.json" "dist\全量自动化客服质检系统\config\ai_config.json" >nul
xcopy /E /I /Y docs "dist\全量自动化客服质检系统\docs" >nul
if exist "README_给同事.md" copy /Y "README_给同事.md" "dist\全量自动化客服质检系统\README_给同事.md" >nul
if not exist "dist\全量自动化客服质检系统\data" mkdir "dist\全量自动化客服质检系统\data"

echo [DONE] dist\全量自动化客服质检系统
pause
