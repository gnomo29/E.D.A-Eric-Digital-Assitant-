@echo off
chcp 65001 >nul
title E.D.A. - Setup DEBUG (mantiene ventana abierta)
color 0A

cls

echo.
echo ========================================
echo   E.D.A. - Setup DEBUG
echo   La ventana NO se cerrará sola
echo ========================================
echo.
pause

echo Verificando Python...
python --version
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Python no encontrado
    pause
    exit /b 1
)
echo.
pause

echo Verificando carpeta actual...
cd
dir requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] El archivo requirements.txt no existe aquí
    echo Asegúrate de estar en la carpeta EDA_Project
    pause
    exit /b 1
)
echo.
pause

echo Creando/verificando entorno virtual...
if not exist "venv312\Scripts\activate.bat" (
    echo Creando venv312...
    python -m venv venv312
    if %errorlevel% neq 0 (
        echo [ERROR] No se pudo crear venv
        pause
        exit /b 1
    )
)
echo [OK] venv312 existe
echo.
pause

echo Activando entorno virtual...
call venv312\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo [ERROR] No se pudo activar venv
    pause
    exit /b 1
)
echo [OK] Entorno activado
echo.
pause

echo Actualizando pip...
python -m pip install --upgrade pip
echo.
pause

echo Instalando dependencias...
echo (Esto puede tardar varios minutos)
echo.
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Fallo al instalar dependencias
    pause
    exit /b 1
)
echo.
echo [OK] Dependencias instaladas
pause

echo Instalando pipwin...
pip install pipwin
echo.
pause

echo Instalando PyAudio con pipwin...
pipwin install pyaudio
echo.
echo [OK] PyAudio instalado (puede tener advertencias)
pause

echo.
echo ========================================
echo   Setup completado
echo ========================================
echo.
echo Presiona cualquier tecla para lanzar E.D.A...
pause

echo.
echo Lanzando E.D.A...
echo.
python main.py

echo.
echo ========================================
echo E.D.A. se cerró
echo ========================================
pause
