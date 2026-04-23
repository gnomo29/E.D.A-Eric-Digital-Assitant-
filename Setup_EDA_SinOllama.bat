@echo off
chcp 65001 >nul
title E.D.A. - Setup Completo (Sin verificar Ollama)
color 0A
setlocal enabledelayedexpansion

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

echo [Python detectado correctamente]
echo.

echo [PASO 1/5] Verificando entorno virtual...
if not exist "venv312\Scripts\activate.bat" (
    echo.
    echo Creando entorno virtual (venv312)...
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
echo [PASO 2/5] Activando entorno virtual...
call venv312\Scripts\activate.bat
if !errorlevel! neq 0 (
    echo [ERROR] No se pudo activar el entorno virtual
    pause
    exit /b 1
)
echo [OK] Entorno virtual activado

echo.
echo [PASO 3/5] Actualizando pip...
python -m pip install --upgrade pip >nul 2>&1
echo [OK] Pip actualizado

echo.
echo [PASO 4/5] Instalando dependencias...
echo (Esto puede tardar 5-10 minutos en la primera vez)
echo.
pip install -r requirements.txt
if !errorlevel! neq 0 (
    echo [ERROR] No se pudieron instalar las dependencias
    echo Revisa tu conexión a internet
    pause
    exit /b 1
)
echo [OK] Dependencias instaladas

echo.
echo [PASO 5/5] Instalando PyAudio...
pip install pipwin >nul 2>&1
pipwin install pyaudio >nul 2>&1
if !errorlevel! neq 0 (
    echo [WARNING] PyAudio puede tener problemas
    echo E.D.A. funcionará en modo texto si no hay voz
)
echo [OK] PyAudio configurado

echo.
echo ========================================
echo   Setup completado exitosamente!
echo ========================================
echo.
echo NOTA: Si Ollama no está corriendo, E.D.A.
echo      funcionará con capacidades limitadas.
echo      Puedes instalar Ollama desde:
echo      https://ollama.com/download
echo.
echo Iniciando E.D.A...
echo.
timeout /t 2 /nobreak >nul

python main.py

if !errorlevel! neq 0 (
    echo.
    echo [ERROR] E.D.A. se cerró con error
    echo Revisa logs/eda.log para más detalles
)

pause
