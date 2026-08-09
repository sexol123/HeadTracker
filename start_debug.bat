@echo off
title HeadTracker v0.1 [DEBUG]
cd /d "%~dp0"
echo ================================
echo   HeadTracker v0.1
echo   Debug mode (file + console logging)
echo ================================
echo.
python main.py -debug
if errorlevel 1 (
    echo.
    echo [ERROR] Application exited with error.
    echo Press any key to exit...
    pause >nul
)
