@echo off
setlocal
cd /d "%~dp0"
title Building Central RGB
echo ============================================
echo   Building Central RGB
echo ============================================
echo.

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY goto nopython
%PY% --version || goto nopython

echo.
echo [1/3] Installing build tools...
%PY% -m pip install --upgrade pip >nul
%PY% -m pip install --upgrade -r requirements.txt pyinstaller || goto fail

echo.
echo [2/3] Packaging "Central RGB.exe"...
%PY% -m PyInstaller --noconfirm --clean --onedir --windowed --uac-admin --distpath dist_app ^
    --collect-all customtkinter --collect-all pythonnet --collect-all clr_loader --hidden-import clr ^
    --hidden-import PIL._tkinter_finder --hidden-import pystray._win32 --hidden-import encodings.idna --icon central_rgb.ico ^
    --add-data "central_rgb.ico;." --add-data "central_rgb.png;." --add-data "presets;presets" --name "Central RGB" central_rgb.py || goto fail
%PY% -m PyInstaller --noconfirm --onefile --windowed --uac-admin ^
    --collect-all customtkinter --collect-all pythonnet --collect-all clr_loader --hidden-import clr ^
    --hidden-import PIL._tkinter_finder --hidden-import pystray._win32 --hidden-import encodings.idna --icon central_rgb.ico ^
    --add-data "central_rgb.ico;." --add-data "central_rgb.png;." --add-data "presets;presets" --name "Central RGB" central_rgb.py || goto fail

echo.
echo [3/3] Building the installer...
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" goto noinno
"%ISCC%" /Q central_rgb.iss || goto fail
echo.
echo ============================================
echo   Done!
echo   Installer:   installer\CentralRGB-Setup.exe   (run this to install)
echo   Portable:    dist\Central RGB.exe
echo ============================================
explorer installer
pause
exit /b 0

:noinno
echo Inno Setup isn't installed, so only the portable .exe was built.
echo To also build the installer, install Inno Setup (free) and run build.bat again:
echo     winget install JRSoftware.InnoSetup      or   https://jrsoftware.org/isdl.php
echo.
echo   Portable:    dist\Central RGB.exe
explorer dist
pause
exit /b 0

:nopython
echo Python 3 was not found.
echo Install it from https://www.python.org/downloads/
echo IMPORTANT: tick "Add python.exe to PATH" in the installer, then run build.bat again.
start "" https://www.python.org/downloads/
pause
exit /b 1

:fail
echo.
echo Build failed - see the messages above.
pause
exit /b 1
