@echo off
title HeadTracker Tests
cd /d "%~dp0"
echo ================================
echo   HeadTracker test suite
echo ================================
set FAILED=0
for %%f in (tests\test_*.py) do (
    echo.
    echo --- Running %%f ---
    python "%%f"
    if errorlevel 1 (
        echo [FAIL] %%f
        set FAILED=1
    ) else (
        echo [PASS] %%f
    )
)
echo.
if "%FAILED%"=="1" (
    echo [RESULT] SOME TESTS FAILED
    pause >nul
    exit /b 1
) else (
    echo [RESULT] ALL TESTS PASSED
)
