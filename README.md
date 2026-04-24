# E.D.A. (Enhanced Digital Assistant) - Proyecto Completo

Asistente estilo JARVIS para Windows 10/11 (también ejecutable en Linux/macOS con funciones degradadas).

E.D.A. integra:
- Interfaz gráfica futurista con `tkinter`
- IA local con **Ollama + llama3.2:1b**
- Voz (STT + TTS) en español
- Resolución técnica web inteligente (`eda/web_solver.py`)
- Automatización de sistema, mouse/teclado, portapapeles
- Escaneo Bluetooth con `bleak`
- Autoevolución de código con backups automáticos y validación AST

Guía para principiantes (en la carpeta `docs/`):
- `docs/GUIA_NOVATO_CODIGO.md`
- `docs/GUIA_LIBRERIAS_Y_EXTENSIONES.md` (librerías, extensiones y buenas prácticas)
- `docs/EJEMPLOS_CAPACIDADES_EDA.txt` (frases de ejemplo por capacidad; mantener al día con el código)
- Índice breve: `docs/README.md`

En Windows, instalación y arranque rápido: ejecutables en `scripts/windows/` (por ejemplo `Iniciar_EDA.bat`, `INSTALAR_EDA.cmd`). Esos scripts hacen `cd` a la raíz del proyecto automáticamente.

---

## 1) Requisitos del sistema

### Recomendado
- Windows 10/11
- 8GB RAM
- Python 3.10+
- Ollama instalado y funcionando

### Dependencias de Python
Instalación:
```bash
pip install -r requirements.txt
```

---

## 2) Instalación paso a paso

1. Descomprime el proyecto.
2. Abre terminal dentro de la carpeta del proyecto.
3. (Opcional) crea entorno virtual:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```
4. Instala librerías:
   ```bash
   pip install -r requirements.txt
   ```
5. Ejecuta:
   ```bash
   python main.py
   ```

O desde el Explorador de archivos, en `scripts/windows/`, doble clic en `Iniciar_EDA.bat` (requiere `venv312` en la raíz del proyecto, como indica el propio script).

### Pruebas rápidas (recomendado antes de cambios grandes)
```bash
python -m unittest discover -s tests -p "test_*.py"
```
Incluye comprobaciones de memoria, recordatorios, NLP (`parse_command`), web y capas avanzadas. Si falta algún paquete (p. ej. `requests`, `bs4`), instálalo con `pip` antes de ejecutar la suite completa.

### Health check del entorno
```bash
python health_check.py
```

Seguridad configurable:
- En `eda/config.py`, cambia `ASK_PERMISSION_FOR_SENSITIVE_ACTIONS = True/False` para activar o desactivar la petición de permiso antes de acciones sensibles.

---

## 3) Configurar Ollama (obligatorio para IA local)

1. Instala Ollama desde: https://ollama.com
2. Descarga el modelo:
   ```bash
   ollama pull llama3.2:1b
   ```
3. Inicia servicio:
   ```bash
   ollama serve
   ```
4. Verifica en otra terminal:
   ```bash
   ollama list
   ```

Si Ollama no está activo, E.D.A. entra en modo degradado y te avisará.

### 3.1) LLM remoto (opcional)

Por defecto **no se usa** ningún proveedor en la nube: quien clone el repo no necesita API keys.

Si querés un modelo remoto (OpenAI u otro endpoint compatible con `/chat/completions`):

1. Copiá `.env.example` a `.env` y rellená las variables `EDA_REMOTE_LLM_*`, **o** definí esas variables en el sistema.
2. Ajustá `EDA_REMOTE_LLM_MODE` según el uso: `fallback` (cuando Ollama no responde), `research` (síntesis en `web_solver`), `code_review` (revisión de código generado en autoaprendizaje), `research_and_review` (ambos).

La GUI muestra el estado en **Configuración**; `python health_check.py` incluye líneas `remote_llm` y `remote_llm_mode`.

---

## 4) Configurar voz en español

## 4.1 TTS (pyttsx3)
- E.D.A. selecciona automáticamente una voz en español si está disponible.
- Si no encuentra voz español, usa la predeterminada del sistema.

## 4.2 STT (speech_recognition + pyaudio)
En Windows, `pyaudio` puede requerir wheel compilada.

Opciones:
1. Intentar directo:
   ```bash
   pip install pyaudio
   ```
2. Si falla, instalar wheel compatible con tu versión de Python.
3. Reiniciar aplicación.

---

## 5) Configurar Bluetooth (`bleak`)

Instala con:
```bash
pip install bleak
```

Notas:
- Requiere adaptador Bluetooth activo.
- En Windows, permisos y drivers deben estar correctos.
- Si falla, E.D.A. no crashea: responde en modo degradado.

---

## 6) Estructura del proyecto

```text
EDA_Project/
├── main.py                 # Arranque (importa el paquete eda)
├── health_check.py         # Delegación a eda.health_check
├── requirements.txt
├── pyproject.toml          # Metadatos / instalación opcional con pip
├── .env.example            # Plantilla de variables (p. ej. LLM remoto); no incluye secretos
├── README.md
├── eda/                    # Código de la aplicación (paquete Python)
│   ├── __init__.py
│   ├── config.py
│   ├── gui.py
│   ├── core.py
│   ├── remote_llm.py       # Cliente opcional API compatible OpenAI
│   ├── improvement_planner.py
│   ├── audit_log.py
│   ├── voice.py
│   ├── nlp_utils.py
│   ├── actions.py
│   ├── mouse_keyboard.py
│   ├── file_manager.py
│   ├── memory.py
│   ├── web_search.py
│   ├── web_solver.py
│   ├── bluetooth_manager.py
│   ├── integration_hub.py
│   ├── obs_controller.py
│   ├── objective_planner.py
│   ├── multimodal.py
│   ├── optimizer.py
│   ├── evolution.py
│   ├── skills_auto.py
│   ├── security_levels.py
│   ├── scheduler.py
│   ├── system_info.py
│   ├── clipboard.py
│   ├── logger.py
│   ├── utils.py
│   └── health_check.py
├── docs/
│   ├── README.md
│   ├── GUIA_NOVATO_CODIGO.md
│   ├── GUIA_LIBRERIAS_Y_EXTENSIONES.md
│   └── EJEMPLOS_CAPACIDADES_EDA.txt
├── scripts/
│   └── windows/
│       ├── Iniciar_EDA.bat
│       ├── Iniciar_EDA_Silencioso.vbs
│       ├── INSTALAR_EDA.cmd
│       ├── Instalar_y_Lanzar_EDA.bat
│       ├── Setup_EDA_Debug.bat
│       ├── Setup_EDA_SinOllama.bat
│       └── Setup_y_Lanzar_EDA.bat
├── tests/
├── memory/
│   ├── memoria.json
│   ├── bluetooth_devices.json
│   └── solutions_cache.json
├── solutions/
├── captures/
├── backups/
├── logs/
└── suggestions/
```

---

## 7) Comandos de voz y texto (ejemplos)

- "E.D.A., abre notepad"
- "Jarvis, optimiza el sistema"
- "E.D.A., escanea bluetooth"
- "Investiga parpadeo LED Arduino sin delay" (comando forzado de investigación en `eda/core.py`)
- "Busca tutoriales de Python" / "Consulta el precio del dólar" (intención `search_web` en `eda/nlp_utils.py`; la consulta va en `entity` del comando parseado)
- "Muéstrame estado de cpu y ram"

**Preguntas con `?`:** las que empiezan como orden (p. ej. "¿abre Chrome?", "sube el volumen?") no se tratan como solo “pregunta de conocimiento” para abrir investigación web; las dudas tipo “¿Qué es un agujero negro?” sí pueden activar el flujo de investigación según permisos (lógica en `eda/core.py`, `is_research_like_query`).

Lista ampliada de frases: `docs/EJEMPLOS_CAPACIDADES_EDA.txt`.

Wake words soportadas:
- `E.D.A.`
- `eda`
- `jarvis`

---

## 8) `eda/web_solver.py` (módulo crítico)

Pipeline:
1. Busca en fuentes técnicas (DuckDuckGo + StackOverflow + Arduino Forum)
2. Hace scraping con `requests` + `beautifulsoup4`
3. Sintetiza respuesta con Ollama
4. Cachea solución en `memory/solutions_cache.json`
5. Si no puede resolver, abre navegador como fallback

### Ejemplo de uso directo
```python
from eda.web_solver import WebSolver

solver = WebSolver()
result = solver.solve("Cómo parpadear LED en Arduino sin delay")
print(result["answer"])
```

### Generación de código
```python
code = solver.generate_code("Control de servo con botón", language="arduino")
print(code)
```

---

## 9) Autoevolución (`eda/evolution.py`) - cómo funciona

Características:
- Hace backup **antes** de modificar archivo
- Valida sintaxis Python con `ast.parse()`
- Registra eventos en log
- Guarda sugerencias en `suggestions/`

### Backups
- Locales: `backups/YYYY-MM-DD_HH-MM-SS/...`
- Ruta objetivo Windows (cuando esté disponible):
  - `C:\Users\Eric\Desktop\EDA_Backups\YYYY-MM-DD_HH-MM-SS\...`

Si la ruta Windows no existe (por ejemplo, ejecutando en Linux), E.D.A. continúa sin fallar.

---

## 10) Confirmaciones obligatorias

Operaciones críticas (apagar, reiniciar, cerrar procesos) solicitan confirmación.
Esto está centralizado en `eda/actions.py` + callback GUI.

---

## 11) Troubleshooting

## 11.1 "No tengo conexión con Ollama"
- Ejecuta `ollama serve`
- Verifica que el modelo exista: `ollama list`
- Revisa `eda/config.py` (`OLLAMA_MODEL = "llama3.2:1b"`)

## 11.2 El micrófono no activa
- Verifica permisos de micrófono en Windows
- Reinstala `speechrecognition` y `pyaudio`
- Prueba otro dispositivo de entrada

## 11.3 pyautogui falla
- Ejecuta con permisos de usuario adecuados
- Asegura que la sesión de escritorio esté activa

## 11.4 Bluetooth vacío
- Revisa que Bluetooth esté encendido
- Prueba con dispositivos cercanos y visibles
- Reinstala `bleak`

## 11.5 GUI no abre
- Verifica Python con soporte `tkinter`
- Prueba `python -m tkinter`

---

## 12) Registro y logs

- Log principal: `logs/eda.log`
- Incluye arranque, errores, acciones y evolución

---

## 13) Ejecución rápida para Eric

```bash
pip install -r requirements.txt
python main.py
```

Listo: E.D.A. inicia GUI y queda operativo inmediatamente.

---

## 14) Preparar para GitHub

Este proyecto ya incluye `.gitignore` para excluir elementos locales/no versionables:
- Entornos virtuales (`venv312/`, `.venv/`)
- Logs, exports, backups y capturas
- Estado local (`memory/*.json`)

Archivos plantilla incluidos para memoria:
- `memory/memoria.example.json`
- `memory/bluetooth_devices.example.json`
- `memory/solutions_cache.example.json`

Flujo recomendado:
```bash
python -m unittest discover -s tests -p "test_*.py"
git add .
git commit -m "prepare project for github"
```

---

## 15) Instalación completa (desde cero)

Guía recomendada para Windows 10/11, paso a paso.

### 15.1 Instalar herramientas base
1. Instala Python 3.12+ desde [python.org](https://www.python.org/downloads/).
   - Marca la opción **Add Python to PATH** durante la instalación.
2. Verifica instalación:
   ```bash
   python --version
   pip --version
   ```
3. (Opcional pero recomendado) Instala Git desde [git-scm.com](https://git-scm.com/download/win).
4. Instala Ollama desde [ollama.com](https://ollama.com/download).

### 15.2 Descargar proyecto y crear entorno virtual
En terminal, dentro de la carpeta donde quieras trabajar:
```bash
python -m venv .venv
.venv\Scripts\activate
```

### 15.3 Instalar dependencias
Con el entorno activado:
```bash
pip install -r requirements.txt
```

### 15.4 Configurar Ollama
```bash
ollama pull llama3.2:1b
ollama serve
```
En otra terminal:
```bash
ollama list
```

### 15.5 Verificación rápida
```bash
python health_check.py
python -m unittest discover -s tests -p "test_*.py"
```

### 15.6 Ejecutar E.D.A.
```bash
python main.py
```

Si algo falla:
- revisa `logs/eda.log`
- revisa sección `11) Troubleshooting`

---

