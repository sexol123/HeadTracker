@echo off
title HeadTracker Setup
cd /d "%~dp0"

echo ================================
echo   HeadTracker Setup
echo ================================
echo.

:: ── Check Python ───────────────────────────────────────────────
echo [1/3] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    py --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo.
        echo [!] Python not found.
        echo.
        echo Would you like to download and install Python 3.11?
        echo (opens browser, run installer, then come back here)
        echo.
        choice /c YN /m "Open download page?"
        if errorlevel 2 (
            echo Setup cancelled.
            pause
            exit /b 1
        )
        start https://www.python.org/downloads/
        echo.
        echo After installing Python, re-run this script.
        pause
        exit /b 1
    ) else (
        set PYTHON=py
    )
) else (
    set PYTHON=python
)

%PYTHON% --version
echo.

:: ── Check pip ──────────────────────────────────────────────────
echo [2/3] Checking pip...
%PYTHON% -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] pip not found, installing...
    %PYTHON% -m ensurepip --default-pip
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install pip.
        pause
        exit /b 1
    )
)
echo pip OK
echo.

:: ── Install dependencies ───────────────────────────────────────
echo [3/3] Installing dependencies...
echo.

%PYTHON% -m pip install --upgrade pip
%PYTHON% -m pip install mediapipe opencv-python PySide6 numpy pynput

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Some packages failed to install.
    echo Try running this script as Administrator.
    pause
    exit /b 1
)

:: ── Download model if missing ──────────────────────────────────
if not exist "models\face_landmarker.task" (
    echo.
    echo Downloading face landmark model...
    mkdir models 2>nul
    %PYTHON% -c "import urllib.request; urllib.request.urlretrieve('https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task', 'models/face_landmarker.task')"
    if %errorlevel% neq 0 (
        echo [WARNING] Model download failed. You can download it manually:
        echo   https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task
        echo   Place it in: models\face_landmarker.task
    ) else (
        echo Model downloaded OK
    )
)

:: ── Create logs dir ────────────────────────────────────────────
mkdir logs 2>nul

:: ── Done ───────────────────────────────────────────────────────
echo.
echo ================================
echo   Setup complete!
echo ================================
echo.
echo Run:  start.bat
echo.
pause
