# E.D.A. — Enhanced Digital Assistant

Asistente de escritorio estilo JARVIS (Windows 10/11 principalmente; en Linux/macOS parte de las funciones se degrada con elegancia).

## Qué hace

| Área | Detalle breve |
|------|----------------|
| Interfaz | GUI `tkinter`, chat, panel de estado |
| IA local | [Ollama](https://ollama.com) (`eda/core.py`) — modelo por defecto en `eda/config.py` |
| IA remota | **Opcional** — API compatible OpenAI; ver `.env.example` y sección *LLM remoto* |
| Voz | TTS (`pyttsx3`) + STT (`speech_recognition`) en español |
| Sistema | Apps, volumen, brillo, Bluetooth, optimización (`eda/actions.py`, etc.) |
| Web | Búsqueda, scraping acotado, síntesis (`eda/web_solver.py`) |
| Spotify | **Opcional:** Web API (`spotipy` + `.env`) o fallback escritorio (URI + atajos) |
| Memoria | JSON local bajo `memory/` (archivos reales ignorados por Git; hay `.example.json`) |
| Código | Autoaprendizaje con confirmación, evolution con backup (`eda/evolution.py`) |

## Inicio rápido

```bash
cd EDA_Project
python -m venv venv312
venv312\Scripts\activate
pip install -r requirements.txt
python main.py
```

**Windows — instalación automática:** con **`scripts/windows/INSTALAR_EDA.cmd`** podés instalar **todo de una vez**: comprueba **Python 3.12** (`py -3.12`), recrea el entorno **`venv312`**, instala **`requirements.txt`**, intenta **PyAudio** (pipwin / pip) y al final puede lanzar la GUI. Ejecutalo con doble clic o desde `cmd` en la raíz del repo. Para el día a día, **`scripts/windows/Iniciar_EDA.bat`** solo activa `venv312` y arranca `python main.py` (Ollama se intenta en segundo plano).

**CLI de prueba:** `python main.py --cli`

**Tests:** `python -m unittest discover -s tests -p "test_*.py"`

**Salud del entorno:** `python health_check.py`

## Ollama

1. Instalar Ollama y ejecutar `ollama serve`.
2. `ollama pull llama3.2:1b` (o el modelo definido en `OLLAMA_MODEL` dentro de `eda/config.py`).
3. Si Ollama no está, E.D.A. usa fallbacks (web / mensaje degradado) según el flujo.

## LLM remoto (opcional)

Por defecto **no** se llama a ninguna nube. Quien clone el repo no necesita API keys.

1. Copiar `.env.example` → `.env` y completar `EDA_REMOTE_LLM_*`, **o** exportar las mismas variables en el sistema.
2. Modo `EDA_REMOTE_LLM_MODE`: `off` | `fallback` | `research` | `code_review` | `research_and_review` (detalle en comentarios de `eda/config.py`).

Estado visible en la GUI (**Configuración**) y en `health_check.py`.

## Spotify (opcional, repo público)

1. App en [Spotify for Developers](https://developer.spotify.com/) — redirect **`http://127.0.0.1:8888/callback`** (o la que definas en `EDA_SPOTIFY_REDIRECT_URI`).
2. **PKCE (sin client secret):** `EDA_SPOTIFY_CLIENT_ID` + `EDA_SPOTIFY_USE_PKCE=1` en `.env`.  
   **O** app con secret: `EDA_SPOTIFY_CLIENT_ID` + `EDA_SPOTIFY_CLIENT_SECRET` (no subir a Git).
3. Primera vez (o token caducado): podés ejecutar `python scripts/spotify_login.py` a mano; el token queda en **`.cache/`** (ignorado por Git). Si falta caché o la API responde **401 / token inválido**, al reproducir música E.D.A. puede **lanzar ese script solo** y reintentar una vez. Desactivar: `EDA_SPOTIFY_AUTO_LOGIN=0` en `.env`.
4. Sin configuración, E.D.A. sigue usando el **modo escritorio** (como antes). El control remoto vía API suele requerir **Premium** y un cliente Spotify abierto.

`python health_check.py` muestra `spotify_web` y `optional:spotipy`.

## Documentación y ejemplos

| Ruta | Contenido |
|------|------------|
| `docs/README.md` | Índice de la carpeta `docs/` |
| `docs/GUIA_NOVATO_CODIGO.md` | Recorrido por módulos |
| `docs/GUIA_LIBRERIAS_Y_EXTENSIONES.md` | Dependencias y prácticas |
| `docs/EJEMPLOS_CAPACIDADES_EDA.txt` | Frases de prueba (voz / texto) |
| `scripts/windows/README.md` | Lanzadores Windows |

Wake words habituales: `E.D.A.`, `eda`, `jarvis`.

## Estructura del repositorio

```text
EDA_Project/
├── main.py              # Entrada: GUI o --cli
├── health_check.py      # Wrapper → eda.health_check
├── requirements.txt
├── pyproject.toml
├── .env.example
├── eda/                 # Paquete principal (GUI, core, web_solver, memory, …)
├── docs/
├── scripts/windows/     # .bat / .cmd / .vbs
├── tests/
├── memory/              # *.json runtime en .gitignore; solo *.example.json en Git
├── logs/ backups/ …     # Generados en ejecución (ignorados)
└── …
```

## Configuración útil

- **Permisos GUI** y familia de acciones: panel **Permisos** en la aplicación; persisten en memoria.
- **Confirmaciones sensibles:** `ASK_PERMISSION_FOR_SENSITIVE_ACTIONS` en `eda/config.py`.
- **Ollama:** `OLLAMA_MODEL`, URLs en `eda/config.py`.

## Web solver (resumen)

Flujo típico: búsqueda (p. ej. DuckDuckGo) → scrape limitado → síntesis con Ollama o LLM remoto (según modo) → caché en `memory/solutions_cache.json`. Uso programático: `from eda.web_solver import WebSolver`.

## Autoevolución

`EvolutionEngine`: backup antes de escribir, validación `ast.parse()`, sugerencias en `suggestions/`. La autoevolución “en bloque” del menú normaliza finales de línea en `.py` del proyecto; el autoaprendizaje confirmado por el usuario puede añadir funciones a módulos elegidos (p. ej. `eda/skills_auto.py`).

## Problemas frecuentes

| Síntoma | Qué revisar |
|---------|----------------|
| Sin Ollama | `ollama serve`, `ollama list`, firewall local |
| Micrófono | Permisos Windows; `pyaudio` / `speechrecognition` |
| Sin Bluetooth | Adaptador encendido; paquete `bleak` |
| GUI no abre | `python -m tkinter` |
| pyautogui | Sesión de escritorio activa; permisos de usuario |

Log principal: `logs/eda.log`.

## Git y colaboración

`.gitignore` excluye `.env`, `venv*/`, `memory/*.json` (no los `.example.json`), logs, backups, etc. **No subir** claves ni `memoria.json` personal.

```bash
python -m unittest discover -s tests -p "test_*.py"
git add -A
git commit -m "Tu mensaje"
git push origin main
```

## Licencia

Ver archivo `LICENSE` en la raíz del proyecto.
