@echo off
chcp 65001 >nul
title E.D.A. - Setup Completo
color 0A
setlocal enabledelayedexpansion

cd /d "%~dp0..\..\.."

cls

echo.
echo ========================================
echo   E.D.A. - Eric's Digital Assistant
echo   Setup Completo y Lanzamiento
echo ========================================
echo.

REM Verificar si Python está instalado
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python no está instalado o no está en PATH
    echo Por favor instala Python 3.12 desde: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Verificar si Ollama está instalado (no crítico)
ollama --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Comando 'ollama' no encontrado en PATH
    echo        Ollama puede estar corriendo como servicio de fondo
    echo        Continuando de todas formas...
) else (
    echo [OK] Ollama detectado
)

echo [PASO 1/6] Verificando entorno virtual...
if not exist "venv312\Scripts\activate.bat" (
    echo.
    echo [PASO 1/6] Creando entorno virtual (venv312)...
    python -m venv venv312
    if !errorlevel! neq 0 (
        echo [ERROR] No se pudo crear el entorno virtual
        pause
        exit /b 1
    )
    echo [OK] Entorno virtual creado
) else (
    echo [OK] Entorno virtual detectado
)

echo.
echo [PASO 2/6] Activando entorno virtual...
call venv312\Scripts\activate.bat
if !errorlevel! neq 0 (
    echo [ERROR] No se pudo activar el entorno virtual
    pause
    exit /b 1
)
echo [OK] Entorno virtual activado

echo.
echo [PASO 3/6] Actualizando pip...
python -m pip install --upgrade pip >nul 2>&1
if !errorlevel! neq 0 (
    echo [WARNING] Pip update falló, continuando...
)
echo [OK] Pip actualizado

echo.
echo [PASO 4/6] Instalando dependencias (esto puede tardar 5-10 minutos)...
pip install -r requirements.txt
if !errorlevel! neq 0 (
    echo [ERROR] No se pudieron instalar las dependencias
    pause
    exit /b 1
)
echo [OK] Dependencias instaladas

echo.
echo [PASO 5/6] Instalando PyAudio...
pip install pipwin >nul 2>&1
pipwin install pyaudio
if !errorlevel! neq 0 (
    echo [WARNING] PyAudio installation may have issues
    echo Continuando de todas formas...
)
echo [OK] PyAudio configurado

echo.
echo ========================================
echo   Setup completado exitosamente!
echo ========================================
echo.
echo [PASO 6/6] Iniciando E.D.A...
echo.
timeout /t 2 /nobreak >nul

REM Iniciar Ollama en segundo plano si no está corriendo
echo Verificando si Ollama está corriendo...
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if "%ERRORLEVEL%"=="1" (
    echo Ollama no detectado en procesos.
    echo Intentando iniciar...
    start /B ollama serve >nul 2>&1
    timeout /t 3 /nobreak >nul
    echo Si Ollama no inicia, E.D.A. funcionará con capacidades limitadas.
) else (
    echo [OK] Ollama ya está corriendo
)

echo Lanzando E.D.A...
python main.py

if !errorlevel! neq 0 (
    echo.
    echo [ERROR] E.D.A. se cerró con error
    echo Revisa logs/eda.log para más detalles
)

pause

