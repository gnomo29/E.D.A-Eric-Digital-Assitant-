@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [setup] Creando entorno virtual en .venv ...
  where py >nul 2>nul
  if %errorlevel%==0 (
    py -3 -m venv .venv
  ) else (
    python -m venv .venv
  )
  if errorlevel 1 (
    echo [error] No se pudo crear .venv. Verifica Python instalado.
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
  echo [error] No se pudo activar el entorno virtual .venv.
  exit /b 1
)

python -m pip --version >nul 2>nul
if errorlevel 1 (
  echo [setup] Reparando pip en .venv ...
  python -m ensurepip --upgrade
)

python -m pip install --upgrade pip >nul

if exist ".env" (
  echo [setup] Cargando variables de .env ...
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" (
      if /i not "%%A:~0,1%%"=="#" (
        set "%%A=%%B"
      )
    )
  )
)

python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:11434', timeout=2); sys.exit(0)" >nul 2>nul
if errorlevel 1 (
  echo [error] Ollama no detectado en http://127.0.0.1:11434
  echo [error] Inicia Ollama antes de abrir E.D.A.
  exit /b 2
) else (
  echo [ok] Ollama detectado.
)

python -c "import json,urllib.request,sys; d=json.loads(urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=3).read().decode()); names=[(m.get('name') or '') for m in d.get('models', []) if isinstance(m, dict)]; sys.exit(0 if any(n=='llama3.2:1b' or n.startswith('llama3.2:1b:') for n in names) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [error] Falta el modelo llama3.2:1b en Ollama.
  echo [error] Ejecuta: ollama pull llama3.2:1b
  exit /b 3
) else (
  echo [ok] Modelo llama3.2:1b disponible.
)

python run_assistant.py --auto-install %*
echo [info] Log de instalacion: logs\installer.log
endlocal

