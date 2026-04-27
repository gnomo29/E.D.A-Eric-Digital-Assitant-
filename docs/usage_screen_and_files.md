# Uso: Visión de Pantalla y Organizador de Archivos

Este documento resume cómo usar los dos superpoderes nuevos del asistente:

- Comprensión de pantalla (vision model con Ollama).
- Organización de archivos por extensión con confirmación previa.

## 1) Ejemplos de conversación

### A) Analiza mi pantalla

**Usuario:** `Analiza mi pantalla`  
**Asistente:** `Perfecto. Voy a capturar tu pantalla, optimizar la imagen y analizarla con un modelo de visión local (llava/moondream).`  
**Asistente (respuesta esperada):** `[Visión llava] Veo una terminal con un error de dependencias de audio y sugerencias para instalar PyAudio.`

También puedes pedir:

- `¿Qué hay en mi pantalla?`
- `Explícame este error`
- `Analiza esta pantalla`

### B) Organiza la carpeta Descargas

**Usuario:** `Organiza la carpeta Descargas`  
**Asistente:** `Plan listo para C:\Users\...\Downloads: mover 12 archivos (5 imágenes, 4 documentos, 2 música, 1 ejecutable). Voy a mover 5 imágenes, 4 documentos, 2 música, 1 ejecutable. ¿Procedo con el movimiento real? Responde sí o no.`  
**Usuario:** `Sí`  
**Asistente:** `Organización completada. Movidos: 12 archivo(s).`

Si respondes `No`, el asistente cancela el plan sin mover archivos.

## 2) Ejemplo de plan JSON (previo a ejecutar)

Este es un ejemplo del plan que el asistente prepara antes del movimiento real:

```json
{
  "status": "ok",
  "message": "Plan listo para C:/Users/eric/Downloads: mover 3 archivos (2 imagenes, 1 documentos).",
  "target_directory": "C:/Users/eric/Downloads",
  "moves": [
    {
      "source": "C:/Users/eric/Downloads/foto_001.jpg",
      "destination_dir": "C:/Users/eric/Downloads/Imagenes",
      "destination": "C:/Users/eric/Downloads/Imagenes/foto_001.jpg",
      "bucket": "Imagenes"
    },
    {
      "source": "C:/Users/eric/Downloads/foto_002.png",
      "destination_dir": "C:/Users/eric/Downloads/Imagenes",
      "destination": "C:/Users/eric/Downloads/Imagenes/foto_002.png",
      "bucket": "Imagenes"
    },
    {
      "source": "C:/Users/eric/Downloads/factura.pdf",
      "destination_dir": "C:/Users/eric/Downloads/Documentos",
      "destination": "C:/Users/eric/Downloads/Documentos/factura.pdf",
      "bucket": "Documentos"
    }
  ]
}
```

## 3) Instrucciones rápidas para desarrolladores (tests)

Para CI/headless y pruebas seguras, usa mocks:

### Mock de captura con `pyautogui`

```python
from unittest.mock import patch
from PIL import Image

@patch("eda.vision.pyautogui")
def test_capture(mock_pyautogui):
    mock_pyautogui.screenshot.return_value = Image.new("RGB", (1920, 1080))
    # llamar VisionService().capture_screen()
```

### Mock de movimientos con `shutil`

```python
from unittest.mock import patch

with patch("eda.actions.shutil.move") as mock_move, patch("eda.actions.os.makedirs"):
    # llamar apply_directory_organization_plan(plan)
    mock_move.assert_called()
```

### Ejecutar suite completa

```bash
python -m unittest discover -s tests -p "test_*.py"
```
