@echo off
chcp 65001 >nul
title E.D.A. - Instalacion Automatica
color 0A
setlocal enabledelayedexpansion

cls

echo.
echo ========================================
echo   E.D.A. - Eric's Digital Assistant
echo   Instalacion Automatica
echo ========================================
echo.

REM Cambiar al directorio del script
REM Raíz del proyecto EDA_Project
cd /d "%~dp0..\.."

echo Directorio actual:
cd
echo.

echo Verificando Python 3.12...
py -3.12 --version
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.12 no encontrado
    echo Por favor instala Python 3.12 desde: https://www.python.org/downloads/release/python-3120/
    echo Presiona cualquier tecla para salir...
    pause >nul
    exit /b 1
)
echo [OK] Python 3.12 detectado
echo.

echo Verificando requirements.txt...
if not exist "requirements.txt" (
    echo [ERROR] requirements.txt no encontrado
    echo Asegurate de ejecutar este archivo desde la carpeta EDA_Project
    pause
    exit /b 1
)
echo [OK] requirements.txt encontrado
echo.

echo [1/5] Preparando entorno virtual con Python 3.12...
if exist "venv312" (
    echo Eliminando entorno virtual antiguo...
    rmdir /s /q venv312
)
echo Creando entorno virtual con Python 3.12...
py -3.12 -m venv venv312
if !errorlevel! neq 0 (
    echo [ERROR] No se pudo crear el entorno virtual
    pause
    exit /b 1
)
echo [OK] Entorno virtual creado con Python 3.12
echo.

echo [2/5] Activando entorno virtual...
call venv312\Scripts\activate.bat
if !errorlevel! neq 0 (
    echo [ERROR] No se pudo activar el entorno virtual
    pause
    exit /b 1
)
echo [OK] Entorno activado

echo Verificando version de Python en el entorno...
python --version
echo.

echo [3/5] Instalando dependencias...
echo (Esto tardara 5-10 minutos en la primera vez)
echo.
pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if !errorlevel! neq 0 (
    echo [ERROR] Fallo al instalar dependencias
    pause
    exit /b 1
)
echo [OK] Dependencias instaladas
echo.

echo [4/5] Instalando PyAudio con pipwin...
echo Instalando pipwin primero...
pip install pipwin
if !errorlevel! neq 0 (
    echo [WARNING] Problema al instalar pipwin
)
echo.
echo Instalando PyAudio...
pipwin install pyaudio
if !errorlevel! neq 0 (
    echo [WARNING] pipwin fallo, intentando con pip directamente...
    pip install pyaudio
)
echo [OK] PyAudio configurado
echo.

echo [5/5] Verificando Ollama...
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo [OK] Ollama esta corriendo
) else (
    echo [INFO] Ollama no detectado
    echo        E.D.A. funcionara con capacidades limitadas
)
echo.

echo ========================================
echo   Instalacion completada!
echo ========================================
echo.
echo Presiona cualquier tecla para lanzar E.D.A...
pause >nul

echo.
echo Iniciando E.D.A...
python main.py

if !errorlevel! neq 0 (
    echo.
    echo [ERROR] E.D.A. se cerro con errores
    echo Revisa logs/eda.log para detalles
)

echo.
pause
