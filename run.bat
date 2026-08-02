@echo off
rem KB Previl launcher. Double-click to set up and start the service.
rem Needs Python 3.10+ (the "py" launcher or "python" on PATH). See README.md.
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 run.py %*
) else (
    python run.py %*
)
if errorlevel 1 (
    echo.
    echo [KB Previl] Failed to start. Is Python 3.10+ installed? See README.md.
    pause
)
