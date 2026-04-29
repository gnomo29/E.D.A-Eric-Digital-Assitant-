# E.D.A. (Eric Digital Assistant)

Asistente de IA local para escritorio con interfaz gráfica, comandos por texto/voz, automatización de tareas y módulos de observación del sistema. Está orientado a uso personal en Windows y Linux, con un perfil de ejecución razonable para equipos con 8 GB de RAM.

## Ruta de aprendizaje desde cero

Si quieres entender el proyecto sin experiencia previa, sigue este orden:

1. `docs/00_EMPIEZA_AQUI.md`
2. `docs/01_MAPA_DEL_PROYECTO.md`
3. `docs/GUIA_NOVATO_CODIGO.md`
4. `docs/02_PRIMERA_CONTRIBUCION.md`

## GUÍA PARA NO PROGRAMADORES: Cómo arrancar EDA paso a paso

### Windows (la forma más fácil)

1. Abre esta carpeta del proyecto.
2. Haz doble clic en `INICIAR_ASISTENTE.bat`.
3. Espera a que termine la instalación automática (si falta algo).
4. Se abrirá E.D.A. automáticamente.

### Si Windows muestra advertencias

- Acepta ejecutar el `.bat` si te lo pide.
- Si solicita permisos, ejecuta el archivo con clic derecho -> **Ejecutar como administrador**.

### Entrada principal del asistente

- Archivo de inicio oficial: `start_eda.py`
- Lanzador recomendado para usuarios finales: `INICIAR_ASISTENTE.bat`

## Inicio rápido (recomendado)

- **Windows:** haz doble clic en `INICIAR_ASISTENTE.bat` y listo.
- **Linux/macOS:** ejecuta:

```bash
chmod +x iniciar.sh
./iniciar.sh
```

El lanzador unificado:
- detecta dependencias faltantes y ofrece instalarlas,
- verifica estado de Ollama,
- abre directamente la interfaz principal (`src/ui_main.py`).

## Features

- **UI principal Obsidian** (`src/ui_main.py`) como interfaz activa del proyecto.
- **Modo voz completo**: STT (entrada por micrófono) + TTS (respuesta hablada).
- **Control de sistema**: abrir/cerrar apps, volumen, brillo, ventanas, USB y acciones guiadas.
- **Aprendizaje de tareas** con persistencia local (SQLite + JSON) y reutilización por trigger.
- **Web solver** para investigación técnica y generación de soluciones/código de apoyo.
- **Permisos y confirmaciones** para acciones sensibles desde la interfaz.
- **Scripts de operación** para bootstrap, health check, build y limpieza de runtime.

## Requisitos críticos

- Python **3.12** (recomendado/objetivo principal del entorno `.venv`).
- `pip` actualizado.
- Windows 10/11 o Linux.

## Requisitos previos

- Python **3.10+** (compatibilidad general), con preferencia operativa por **3.12**.
- `pip` actualizado.
- Sistema operativo:
  - **Windows 10/11** (soporte principal).
  - **Linux** (soporte parcial según dependencias de audio/GUI).
- (Opcional) [Ollama](https://ollama.com/) para respuestas locales con LLM.
- Micrófono y salida de audio si usarás voz.

### Si no tienes Python instalado

- Descarga Python desde [python.org](https://www.python.org/downloads/).
- En Windows, activa la opción **Add Python to PATH** durante la instalación.
- Verifica instalación:

```bash
python --version
pip --version
```

## Installation

### 1) Clonar el repositorio

```bash
git clone <URL_DEL_REPO>
cd EDA_Project
```

### 2) Ejecutar el lanzador unificado

- **Windows:** `INICIAR_ASISTENTE.bat`
- **Linux/macOS:** `./iniciar.sh`

El lanzador guía la instalación si falta algo.

### 3) Instalación manual (alternativa)

```bash
py -3.12 -m venv .venv
```

- **Windows**
```bat
.venv\Scripts\activate
pip install -r requirements.txt
```

- **Linux**
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 4) Configurar variables de entorno

```bash
cp .env.example .env
```

En Windows puedes copiarlo manualmente en el Explorador.  
Edita `.env` solo si necesitas integraciones opcionales (por ejemplo Spotify Web API o LLM remoto).

## Configuración de Ollama (opcional, recomendado)

1. Instala Ollama: [https://ollama.com/download](https://ollama.com/download)  
2. Levanta el servicio y descarga un modelo liviano:

```bash
ollama pull llama3.2:1b
```

3. Verifica estado:

```bash
python health_check.py
```

Si Ollama no está disponible, el proyecto sigue funcionando, pero con capacidades reducidas según flujo.

## Usage

### Ejecutar el asistente

- UI principal (predeterminada):
```bash
python run_assistant.py
```

- Modo CLI (opcional):
```bash
python run_assistant.py --cli
```

### Interfaz Obsidian (`src/ui_main.py`)

Interfaz ligera tipo “deep obsidian” orientada a operación segura:

```bash
python src/ui_main.py
```

En CI o máquinas sin pantalla puedes usar `python src/ui_main.py --no-gui` (sale al instante) o exportar `EDA_UI_HEADLESS=1` para que el punto de entrada no abra ventana.

- **RAM:** pensada para equipos con **8 GB de RAM** o más; el uso pico depende del SO y del backend (Tk vs CustomTkinter). Un benchmark de referencia en este repo está en `tools/profiles/ui_peak_report.txt` (generado con `python tools/ui_memory_profile.py`).
- **Métricas (psutil):** el refresco del panel CPU/RAM usa por defecto **2000 ms**. Se puede cambiar con la variable de entorno `EDA_UI_METRICS_MS` o con `--metrics-ms` en la línea de comandos.
- **CustomTkinter:** si `customtkinter` no está disponible, la UI cae automáticamente a **tkinter** (degradado visual mínimo, sin crashear).
- **Hilos y seguridad:** el `ActionAgent` corre en **ThreadPoolExecutor**; los comandos de riesgo medio/alto (y aprendizaje no confiable por defecto) abren un **modal** (Approve / Deny / Approve Once y “Record trust”) antes de ejecutar. Las decisiones quedan en `data/logs/operate_secure_audit.jsonl`.
- **Pruebas:** `python -m unittest discover -s tests -p "test_*.py"` (incluye `tests/test_ui_main.py`, sin GUI real).
- **Benchmark RSS:** `python tools/ui_memory_profile.py` (60 s de muestreo por defecto).

### Uso básico

- Escribe o dicta comandos desde la interfaz.
- Activa/desactiva voz desde el check de respuesta hablada.
- Usa el botón de micrófono para escucha por frase o continua.
- Ajusta permisos y configuración desde el panel lateral.

### Ejemplos de uso reales

- `abre chrome`
- `abre youtube y busca lofi en youtube`
- `ejecuta comando: dir`
- `observar sistema: procesos`
- `mueve archivo: C:\tmp\a.txt -> C:\tmp\b.txt`
- `reproduce metallica en spotify`
- `objetivo organizar trabajo y luego ejecutar siguiente paso`

### Cómo usar (Visión y Organización de Archivos)

---
### Cómo usar — Visión y Organización de Archivos

[INCLUIR EL SNIPPET EXACTO QUE TE PROPORCIONÉ EN LA SECCIÓN 1 de este prompt]
---

#### Cheat sheet rápido

- `Analiza mi pantalla`
- `Organiza la carpeta Downloads`
- `Sí` / `No` para confirmar

## Detección inteligente Web/App

El asistente distingue entre aplicaciones de escritorio y sitios web:

- `abre spotify` -> intenta abrir Spotify como app local.
- `abre youtube` -> detecta web-app y abre `https://www.youtube.com` en navegador.
- `abre example.com` -> normaliza a `https://example.com`.
- `abre localhost:8000` -> abre `http://localhost:8000`.

## Estructura del proyecto

```text
EDA_Project/
├── src/eda/                 # Código fuente principal
├── scripts/                 # Utilidades de build/mantenimiento
├── tools/                   # Herramientas operativas y seguridad
├── tests/                   # Pruebas unitarias
├── docs/                    # Documentación adicional
├── config/                  # Configuración versionada no sensible
├── data/                    # Runtime local (logs, memoria, temp, recursos, backups)
├── main.py                  # Punto de entrada
├── health_check.py          # Diagnóstico de entorno
├── install_deps.py          # Bootstrap de entorno
├── INICIAR_ASISTENTE.bat    # Arranque unificado en Windows
├── iniciar.sh               # Arranque unificado en Linux/macOS
├── requirements.txt
└── pyproject.toml
```

## Dependencias principales

- `requests`, `urllib3`, `beautifulsoup4`
- `pyttsx3`, `SpeechRecognition`
- `pyautogui`, `pygetwindow`, `psutil`
- `duckduckgo-search`, `googlesearch-python`
- `bleak`, `screen-brightness-control`
- `ollama` (cliente Python)
- `obsws-python`, `spotipy` (integraciones opcionales)

Ver lista completa en `requirements.txt`.

## Compatibilidad con 8GB de RAM

- Para la GUI nueva (`src/ui_main.py`), revisa el último `tools/profiles/ui_peak_report.txt` tras ejecutar `tools/ui_memory_profile.py` en tu equipo.
- Recomendado usar modelos livianos en Ollama (ej. `llama3.2:1b`).
- Mantener navegador y apps pesadas cerradas durante sesiones largas.
- Ejecutar mantenimiento periódico de runtime (`scripts/scan_obsolete.py` y limpieza de logs).
- Si detectas presión de memoria, usa preferentemente texto en lugar de voz continua.

## Troubleshooting

- **`No module named ...`**  
  Activa `.venv` e instala dependencias nuevamente con `pip install -r requirements.txt`.

- **Micrófono no detectado / STT falla**  
  Verifica permisos del SO, dispositivo por defecto y prueba con frases más cortas.

- **Sin voz de salida (TTS)**  
  Revisa configuración de audio del sistema y estado del check de voz en UI.

- **Ollama offline**  
  Inicia Ollama, valida con `ollama list` y luego `python health_check.py`.

- **Errores con dependencias en Linux**  
  Instala librerías de sistema necesarias para audio/GUI antes de `pip install`.

### Problemas con voz en Windows (PyAudio)

En Python 3.12/Windows puede fallar la compilación de `pyaudio` (`Failed building wheel for pyaudio`).
El proyecto ahora **no bloquea el arranque**: inicia en modo limitado (sin micrófono/STT continuo) y mantiene GUI + TTS cuando sea posible.

#### Recrear entorno virtual con Python 3.12

```bat
rmdir /s /q .venv
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Pasos recomendados para recuperar voz completa:

1. Activar entorno virtual:
```bat
.venv\Scripts\activate
```
2. Instalar helper de ruedas Windows:
```bat
pip install pipwin
```
3. Instalar PyAudio:
```bat
pipwin install pyaudio
```
4. Si falla, instalar **Build Tools for Visual Studio** (Desktop development with C++) y reintentar.
5. Alternativa estable: usar entorno Conda con `conda-forge`.

Logs del instalador:
- Revisa `data/logs/installer.log` para ver intentos y fallbacks de instalación (`pipwin`, `--only-binary`, rueda local, compilación).

## Desarrollo y calidad

- Ejecutar tests:
```bash
python -m unittest discover -s tests -p "test_*.py"
```

La suite actual incluye **72+ tests** unitarios/integración para intents, orquestador, calidad de respuesta, voz y detección Web/App.

## Seguridad Enterprise/PRO (v2.0)

- **Zero Trust input validation:** sanitización global para comandos, targets de apps y navegación web.
- **Aprobación PRO en acciones críticas:** para `ejecuta comando`, movimientos y borrados, el orquestador exige confirmación explícita `Sí/No` con vista previa de impacto.
- **Sandbox de habilidades aprendidas:** ejecución aislada de tareas aprendidas con timeout de 30 segundos.
- **Redacción automática de secretos/PII:** emails, tokens y credenciales se reemplazan por `[REDACTED]` en logs y persistencia.
- **Memoria cifrada en reposo:** persistencia protegida con `Fernet` (si `cryptography` está disponible) y fallback compatible.

## Plugins (skills)

- Carpeta runtime: `skills/`
- Registro de permisos y estado: `skills/manifest.json`
- Cada plugin `.py` debe exponer funciones seguras (ejemplo: `skills/example_skill.py`).
- Carga recomendada desde `eda.plugin_loader.PluginLoader`.

## Modo Híbrido y Especialistas

- **Modo híbrido online/offline:** `EDACore` desactiva fallback web automáticamente sin conectividad.
- **Especialista Creativo (Blender):** `skills/creative_blender.py` genera scripts y ejecuta `blender --background --python ...` con guard de RAM.
- **Especialista Documental:** `skills/document_specialist.py` crea `.docx`, extrae PDF y genera `.pptx`.
- **Especialista Gaming:** `skills/gaming_specialist.py` soporta URIs Steam (`steam://run/<id>`) y detección local de clientes.
- **Recordatorios locales:** `src/eda/background_tasks.py` preparado para alertas de escritorio en Windows.

## Manual de v3.0: Seguridad, Móvil y Recuperación

- **Firma obligatoria de skills:** usa `python tools/sign_skill.py` para generar llaves locales y firmar `skills/*.py` + `skills/manifest.json`.  
  El cargador (`eda.plugin_loader.PluginLoader`) rechaza plugins sin firma válida.
- **Sandbox reforzado:** habilidades aprendidas se ejecutan con timeout y límites de recursos (CPU/memoria) en plataformas compatibles.
- **Undo Manager:** `Deshaz lo último` revierte la última operación de movimiento registrada en `undo_history.db`.
- **Recordatorios resilientes:** persistencia en `reminders.db` con recuperación automática tras reinicio.
  - `Listar recordatorios`
  - `Cancelar recordatorio <ID>`
- **Conector móvil Opt-In:** antes de usar mensajes móviles, E.D.A. pide consentimiento y configuración de token.
  - `enviar mensaje al móvil: ...`
  - `configurar móvil: telegram|TOKEN|CHAT_ID`
  - **Setup Telegram (BotFather):**
    1. En Telegram abre [@BotFather](https://t.me/BotFather) y crea bot con `/newbot`.
    2. Copia el **Bot Token**.
    3. Escribe al bot al menos un mensaje.
    4. Obtén tu `chat_id` con `https://api.telegram.org/bot<TOKEN>/getUpdates`.
    5. Ejecuta `configurar móvil: telegram|<TOKEN>|<CHAT_ID>`.
- **Deshacer acciones:** comando rápido `Deshazlo` o `Deshaz lo último` para revertir el último movimiento de archivos registrado.
- **Token cifrado:** credenciales móviles se guardan cifradas localmente con el motor de secretos.

### Telegram Webhook (opcional, alternativa a polling)

1. Activa modo webhook en configuración:
   - `TELEGRAM_CONTROL_MODE=webhook`
   - `TELEGRAM_WEBHOOK_SECRET=<secret_largo>`
2. Levanta E.D.A.; el endpoint local queda en:
   - `POST /telegram/webhook`
3. Si estás en desarrollo, expón localhost con:
```powershell
tools/run_ngrok_webhook.ps1
```
4. Registra la URL pública en Telegram (`setWebhook`) y añade el header secret:
   - `X-Telegram-Bot-Api-Secret-Token: <secret_largo>`
5. Para volver a polling:
   - `TELEGRAM_CONTROL_MODE=polling`

Seguridad webhook:
- Rechaza requests sin `secret` válido.
- Filtra por `chat_id` dueño.
- Solo guarda en cola/auditoría hash del payload (`raw_payload_hash`), no payload en claro.

### ACL, Rate-limit y OTP remoto (Telegram)

- Archivo ACL configurable:
  - `config/remote_acl.json`
  - Campos por comando: `pattern`, `level` (`info|safe|critical`), `enabled`.
- Parámetros en `src/eda/config.py`:
  - `REMOTE_ACL_FILE`
  - `REMOTE_OTP_TTL_SECONDS` (default `120`)
- Flujo de seguridad:
  - Comandos remotos pasan por ACL antes de ejecutar.
  - Si ACL marca comando `critical`, E.D.A. envía OTP y exige `confirm <OTP>`.
  - Tras 3 OTP inválidos en 10 minutos, E.D.A. envía alerta por Telegram.
- Auditoría JSONL:
  - `data/logs/remote_commands.log`
  - `data/logs/bootstrap_actions.log`

### Rotación y revocación de firmas (producción)

- Rotación segura de llaves:
```bash
python tools/rotate_keys.py
```
  Opciones:
  - `--dry-run`: simula sin escribir archivos.
  - `--force`: limpia estado temporal previo (`*_new`, `.temp`, `.old`) si corresponde.
  - `--rollback`: restaura llaves/firmas desde `*.old`.

- Revocar / listar / reinstaurar skills:
```bash
python tools/revoke_skill.py revoke example_skill.py --reason "incidente"
python tools/revoke_skill.py list
python tools/revoke_skill.py unrevoke example_skill.py
```

Checklist manual recomendado:
1. Ejecutar `--dry-run`.
2. Confirmar backup en `data/backups/keys_rotation_*`.
3. Rotar llaves y validar carga de plugins.
4. Revocar skills sospechosas y re-ejecutar tests.
5. Si falla validación post-rotación, ejecutar `tools/rotate_keys.py --rollback`.

### Operación segura unificada (SRE)

```bash
python tools/operate_secure.py --dry-run --rotate-keys --smoke-loader --rollback-on-fail --yes
```

Flujo automatizado:
1. Backup de `keys/signatures/revocations` en `data/backups/operate_<timestamp>/`.
2. Rotación de llaves opcional (`--rotate-keys`).
3. Smoke de loader/firma (`--smoke-loader`).
4. Revocación opcional (`--revoke <skill.py> --revoke-reason "..."`) solo si smoke OK.
5. Rollback automático (`--rollback-on-fail`) si hay fallo crítico.
6. Auditoría JSONL en `data/logs/operate_secure_audit.jsonl`.

Flags útiles:
- `--dry-run`
- `--rotate-keys`
- `--smoke-loader`
- `--revoke <skill.py>`
- `--rollback-on-fail`
- `--telegram-smoke` (usa token/chat por env o flags; tokens ofuscados en logs)
- `--timeout 600`

## Operaciones y Mantenimiento v3.0

- **Bootstrap inicial seguro:**
```bash
python tools/bootstrap_v3.py
```
  Este script:
  1) respalda `skills/signatures.json`,
  2) firma skills actuales (sin sobrescribir llaves existentes),
  3) valida integridad anti-manipulación,
  4) rota/comprime logs antiguos,
  5) ejecuta smoke test Telegram opcional con `TELEGRAM_TOKEN` y `TELEGRAM_CHATID`,
  6) corre la suite completa de tests.

- **Modos rápidos CLI:**
```bash
python tools/bootstrap_v3.py --only-sign
python tools/bootstrap_v3.py --no-tests --telegram-smoke --telegram-token $TOKEN --telegram-chat $CHAT
python tools/bootstrap_v3.py --dry-run
```

Nota operativa:
- `--no-tests` activa un flujo rápido donde la validación de integridad se reporta como advertencia no bloqueante si el entorno aún está incompleto (por ejemplo, sin skills cargables en esa máquina), manteniendo el proceso útil para CI/local bootstrap.

- **Firmar una skill nueva sin regenerar llaves:**
```bash
python tools/update_skills.py mi_skill.py
```
  También re-firma `skills/manifest.json` para mantener compatibilidad con `PluginLoader`.

- **Re-firmado completo manual (si agregaste muchas skills):**
```bash
python tools/sign_skill.py
```

- **Variables de entorno Telegram (opcional):**
  - `TELEGRAM_TOKEN`
  - `TELEGRAM_CHATID`

- **CI no interactivo:**
```bash
python tools/bootstrap_v3.py --yes --dry-run --no-tests
```
  En CI, `--yes` habilita modo no interactivo y deja auditoría de acciones ejecutadas/omitidas.

- Diagnóstico de entorno:
```bash
python health_check.py
```

- Candidatos de limpieza runtime:
```bash
python scripts/scan_obsolete.py
```

## Contributing

Si quieres colaborar, abre un issue con:
- contexto del problema,
- pasos de reproducción,
- entorno (OS + versión Python),
- logs relevantes.

Para PRs, prioriza cambios pequeños y testeables.

## Créditos

- Proyecto E.D.A. por Eric Jose Sandi Solir.
- Librerías open source de la comunidad Python.

## Licencia

Este proyecto se distribuye bajo licencia **MIT**.  
Consulta el archivo `LICENSE`.
