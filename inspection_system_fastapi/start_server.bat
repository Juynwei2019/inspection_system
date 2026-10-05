@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

if not exist "alembic.ini" (
    echo [ERROR] Put start_server.bat in the inspection_system_fastapi folder.
    goto :failed
)

set "VENV_PY=%CD%\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [1/5] Detecting an installed Python version...
    set "PY_SELECTOR="
    for %%V in (3.12 3.13 3.14) do (
        if not defined PY_SELECTOR (
            py -%%V -c "import sys" >nul 2>&1
            if not errorlevel 1 set "PY_SELECTOR=-%%V"
        )
    )
    if not defined PY_SELECTOR (
        echo [ERROR] Python 3.12, 3.13, or 3.14 was not found. Install one of these versions and try again.
        goto :failed
    )
    echo Creating virtual environment with Python !PY_SELECTOR!...
    py !PY_SELECTOR! -m venv ".venv"
    if errorlevel 1 (
        echo [ERROR] Could not create the Python virtual environment.
        goto :failed
    )
)

"%VENV_PY%" -c "import sys; assert sys.version_info[:2] in ((3,12),(3,13),(3,14))" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] The existing .venv uses an unsupported Python version. Rename that folder, then run this file again.
    goto :failed
)

echo [2/5] Installing required binary packages...
"%VENV_PY%" -m pip install --disable-pip-version-check --only-binary=:all: --quiet -r "requirements.txt"
if errorlevel 1 (
    echo [ERROR] Package installation failed. Check your internet connection and Python version.
    goto :failed
)

echo [3/5] Applying database migrations...
"%VENV_PY%" -m alembic upgrade head
if errorlevel 1 (
    echo [ERROR] Database migration failed.
    goto :failed
)

echo [4/5] Preparing the administrator account...
"%VENV_PY%" -m app.bootstrap_admin
if errorlevel 1 (
    echo [ERROR] Initial account preparation failed.
    goto :failed
)

echo [5/5] Starting the inspection server...
echo Open http://127.0.0.1:8000/ on this computer.
echo Other computers on the same network can use http://THIS-COMPUTER-IP:8000/
echo Press Ctrl+C to stop the server.
"%VENV_PY%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo Please check the message above.
pause
exit /b 1
