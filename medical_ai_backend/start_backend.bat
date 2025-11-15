@echo off
setlocal
echo =====================================================
echo Avvio automatico Medical AI Backend
echo =====================================================

set "ROOT=%~dp0"
set "VENV_DIR=%ROOT%.venv"
set "BACKEND_DIR=%ROOT%backend"
set "BACKEND_PORT=8001"

if not exist "%BACKEND_DIR%\main.py" (
    echo [ERRORE] Non trovo main.py in %BACKEND_DIR%
    pause
    exit /b 1
)

echo Attivazione ambiente virtuale...
call "%VENV_DIR%\Scripts\activate"
if errorlevel 1 (
    echo [ERRORE] impossibile attivare l'ambiente virtuale.
    pause
    exit /b 1
)

cd /d "%ROOT%"
echo Avvio server API su http://127.0.0.1:%BACKEND_PORT% ...
uvicorn backend.main:app --host 127.0.0.1 --port %BACKEND_PORT% --reload

endlocal

