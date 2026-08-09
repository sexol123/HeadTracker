@echo off
title HeadTracker v0.1
cd /d "%~dp0"
echo ================================
echo   HeadTracker v0.1
echo   Head tracking via webcam
echo ================================
echo.
python main.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] Application exited with error.
    echo Press any key to exit...
    pause >nul
)
