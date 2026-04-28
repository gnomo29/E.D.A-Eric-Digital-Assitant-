@echo off
setlocal
cd /d "%~dp0\.."

python install_deps.py
if errorlevel 1 (
  echo [run] Fallo en bootstrap.
  exit /b 1
)

set "PY=%CD%\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [run] No se encontro Python del entorno virtual.
  exit /b 1
)

"%PY%" main.py %*
endlocal

