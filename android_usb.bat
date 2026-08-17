@echo off
setlocal
REM HeadTracker - USB camera bridge for the Android companion app (HeadTrackerCam).
REM Forwards the phone's WebSocket port to this PC, so HeadTracker can use
REM the phone camera over USB without Wi-Fi (only USB debugging is needed).
set PORT=8080

set ADB=adb
where adb >nul 2>nul
if errorlevel 1 (
    if defined ANDROID_HOME (
        set "ADB=%ANDROID_HOME%\platform-tools\adb.exe"
    ) else (
        set "ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
    )
)

if not exist "%ADB%" (
    echo adb not found in PATH, %%ANDROID_HOME%% or %%LOCALAPPDATA%%\Android\Sdk.
    echo Install Android platform-tools (or Android Studio), then re-run this script.
    exit /b 1
)

echo Checking connected devices...
"%ADB%" devices

"%ADB%" forward tcp:%PORT% tcp:%PORT%
if errorlevel 1 (
    echo.
    echo Failed to set up USB forwarding.
    echo Make sure: USB debugging is enabled on the phone (Developer options),
    echo the phone is connected via cable, and you confirmed the RSA dialog.
    exit /b 1
)

echo.
echo ============================================================
echo   USB bridge ready: the phone's port %PORT% is now local.
echo
echo   In HeadTracker:  Camera tab - Source "WebSocket"
echo   URL:             ws://127.0.0.1:%PORT%/ws
echo
echo   Start the stream in the phone app, then press Start.
echo   To remove the forward later: adb forward --remove tcp:%PORT%
echo ============================================================
exit /b 0