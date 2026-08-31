@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 desktop.py
    goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
    python desktop.py
    goto :end
)

echo.
echo [투자] Python 3 was not found.
echo Install Python 3 and enable "Add Python to PATH", then try again.
pause

:end
endlocal
