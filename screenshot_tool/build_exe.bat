@echo off
title Screenshot-Tool - EXE bauen
color 0A
echo ============================================
echo  Screenshot-Tool wird als EXE gebaut ...
echo ============================================
echo.

:: PyInstaller + Abhaengigkeiten installieren
echo [1/3] Installiere Abhaengigkeiten...
pip install --user Pillow mss pyautogui pywin32 keyboard numpy pyinstaller
if errorlevel 1 (
    echo FEHLER: pip install fehlgeschlagen!
    pause
    exit /b 1
)

echo.
echo [2/3] Baue EXE mit PyInstaller...
echo.

:: Wechsle in das Verzeichnis dieses Skripts
cd /d "%~dp0"

:: PyInstaller-Aufruf
::   --onefile        = alles in eine einzige .exe packen
::   --windowed       = kein schwarzes CMD-Fenster beim Start
::   --name           = Name der EXE
::   --add-data       = Zusatzdateien einbetten (falls vorhanden)
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "ScreenshotTool" ^
    --hidden-import PIL._tkinter_finder ^
    --hidden-import win32gui ^
    --hidden-import win32ui ^
    --hidden-import win32con ^
    --hidden-import win32clipboard ^
    --hidden-import pywintypes ^
    --hidden-import mss ^
    --hidden-import mss.windows ^
    --hidden-import keyboard ^
    --hidden-import pyautogui ^
    --hidden-import numpy ^
    --collect-all mss ^
    --collect-all keyboard ^
    screenshot_tool.py

if errorlevel 1 (
    echo.
    echo FEHLER: PyInstaller ist fehlgeschlagen!
    echo Siehe Fehlermeldung oben.
    pause
    exit /b 1
)

echo.
echo [3/3] Aufraeumen...
:: Build-Ordner und .spec-Datei loeschen (nur dist/ bleibt)
rmdir /s /q build 2>nul
del /q ScreenshotTool.spec 2>nul

echo.
echo ============================================
echo  FERTIG!
echo  Die EXE liegt in:
echo  %~dp0dist\ScreenshotTool.exe
echo ============================================
echo.
echo Druecke eine Taste, um den dist-Ordner zu oeffnen...
pause >nul
explorer "%~dp0dist"
