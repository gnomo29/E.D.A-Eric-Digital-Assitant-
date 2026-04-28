@echo off
chcp 65001 >nul
title E.D.A. - Inicio Rapido
color 0B
setlocal EnableDelayedExpansion

REM Raíz del proyecto EDA_Project (este .bat está en scripts\windows)
cd /d "%~dp0..\..\.."
cls
echo ======================================================
echo               R O U T E L L M ^| E . D . A .
echo ======================================================
echo.
echo [1/3] Iniciando servicio Ollama en segundo plano...
start "" /B ollama serve >nul 2>&1
timeout /t 2 /nobreak >nul
echo      ^> Ollama inicializado (o ya estaba en ejecucion).
echo.
echo [2/3] Activando entorno virtual ^"venv312^"...
if exist "venv312\Scripts\activate.bat" (
    call "venv312\Scripts\activate.bat"
    echo      ^> Entorno virtual activo.
) else (
    echo [ERROR] No se encontro venv312\Scripts\activate.bat
    echo         Cree el entorno con: python -m venv venv312
    pause
    exit /b 1
)
echo.
echo [3/3] Lanzando E.D.A. ...
echo.
python main.py
set "EDA_EXIT=%ERRORLEVEL%"
echo.
if not "%EDA_EXIT%"=="0" (
    echo [AVISO] E.D.A. finalizo con codigo %EDA_EXIT%.
    echo Revise logs\eda.log para mas detalles.
    pause
)

endlocal

