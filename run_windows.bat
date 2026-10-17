@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>nul
    if errorlevel 1 (
        echo Install Python 3.12 x64 from python.org, then run this file again.
        pause
        exit /b 1
    )
    py -3.12 -m venv .venv
    if errorlevel 1 (
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -c "import sys; from importlib.metadata import version; import PySide6.QtWidgets, openpyxl; pins={'PySide6':'6.8.3','PySide6-Addons':'6.8.3','PySide6-Essentials':'6.8.3','shiboken6':'6.8.3','openpyxl':'3.1.5','et-xmlfile':'2.0.0'}; sys.exit(0 if all(version(n)==v for n,v in pins.items()) else 1)" >nul 2>nul
if errorlevel 1 (
    echo Installing application dependencies. Internet is required for this first setup.
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -m seoyoung_pos %*
if errorlevel 1 (
    pause
    exit /b 1
)
exit /b 0
