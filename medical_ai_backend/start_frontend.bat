@echo off
setlocal
echo =====================================================
echo Avvio automatico Medical AI Frontend
echo =====================================================

set "ROOT=%~dp0"
set "FRONT_DIR=%ROOT%frontend"
set "PORT=5500"
set "URL=http://127.0.0.1:%PORT%/index.html"

if not exist "%FRONT_DIR%\index.html" (
    echo [ERRORE] Non trovo frontend\index.html
    pause
    exit /b 1
)

echo Avvio server statico (Ctrl+C per arrestarlo)...
start "frontend-server" cmd /k "cd /d ""%FRONT_DIR%"" && python -m http.server %PORT%"
timeout /t 2 >nul

echo Apertura browser su %URL%
start "" "%URL%"

echo Frontend avviato. La finestra del server resta aperta per servire i file.
echo Premi un tasto per chiudere questo prompt.
pause
endlocal
