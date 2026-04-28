# Documentación E.D.A.

- `GUIA_NOVATO_CODIGO.md` — qué hace cada módulo y por dónde empezar.
- `GUIA_LIBRERIAS_Y_EXTENSIONES.md` — dependencias y buenas prácticas.
- `EJEMPLOS_CAPACIDADES_EDA.txt` — frases de ejemplo para probar la GUI y la voz.
- `operational_runbook.md` — smoke checks, pruebas manuales y comandos de verificación.
- `CHANGELOG.md` — cambios recientes de operación/orquestación.
- Voz en Windows: ver sección de troubleshooting en `../README.md` (PyAudio, pipwin, Build Tools, conda).

Los lanzadores unificados están en la raíz: `../INICIAR_ASISTENTE.bat` y `../iniciar.sh`.

El código de la aplicación está en el paquete Python **`../eda/`** (importar como `from eda.gui import EDAGUI`, etc.).

Variables de entorno opcionales (p. ej. LLM remoto): ver **`../.env.example`** en la raíz del repo.
