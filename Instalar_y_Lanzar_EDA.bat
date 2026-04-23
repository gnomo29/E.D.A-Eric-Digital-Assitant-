@echo off
title E.D.A. - Instalacion y Lanzamiento
color 0A

echo ========================================
echo   E.D.A. - Eric's Digital Assistant
echo ========================================
echo.

REM Verificar si existe el entorno virtual
if not exist "venv312\Scripts\activate.bat" (
    echo [1/4] Creando entorno virtual por primera vez...
    python -m venv venv312
    echo     Entorno virtual creado.
    echo.
    
    echo [2/4] Activando entorno virtual...
    call venv312\Scripts\activate
    echo.
    
    echo [3/4] Instalando dependencias (esto puede tardar unos minutos)...
    pip install --upgrade pip
    pip install -r requirements.txt
    echo.
    
    echo [4/4] Instalando PyAudio...
    pip install pipwin
    pipwin install pyaudio
    echo.
    
    echo ========================================
    echo   Instalacion completada exitosamente
    echo ========================================
    echo.
) else (
    echo Entorno virtual detectado.
    call venv312\Scripts\activate
)

echo Iniciando Ollama...
start /B ollama serve
timeout /t 3 /nobreak >nul

echo Iniciando E.D.A...
echo.
python main.py

pause
