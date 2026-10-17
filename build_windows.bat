@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python 3.12 x64 is required for building. Install it from python.org.
    exit /b 1
)

if not exist ".venv-build\Scripts\python.exe" (
    py -3.12 -m venv .venv-build
    if errorlevel 1 exit /b 1
)

".venv-build\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-dev.txt
if errorlevel 1 exit /b 1

".venv-build\Scripts\python.exe" -m pytest -q
if errorlevel 1 exit /b 1

".venv-build\Scripts\python.exe" scripts\build.py
if errorlevel 1 exit /b 1

echo.
echo Build complete: dist\SeoyoungPOS-Windows-x64-portable.zip
echo Extract the ENTIRE archive and run SeoyoungPOS.exe.
exit /b 0
