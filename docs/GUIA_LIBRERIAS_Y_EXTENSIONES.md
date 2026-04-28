# Guia completa de librerias y extensiones

Esta guia explica las librerias que usa E.D.A., como implementarlas mejor y que errores evitar.

## 1) Como leer esta guia

- **Para que sirve:** el rol de la libreria.
- **Donde se usa en E.D.A.:** archivos del proyecto.
- **Implementacion recomendada:** como usarla sin romper el sistema.
- **Errores comunes:** problemas que aparecen seguido.

## 2) Librerias principales del proyecto

### `requests`
- **Para que sirve:** hacer llamadas HTTP (Ollama, web, APIs).
- **Donde se usa en E.D.A.:** `core.py`, `web_search.py`, `web_solver.py`, `system_info.py`.
- **Implementacion recomendada:**
  - Usa `timeout` siempre.
  - Maneja errores con `try/except requests.RequestException`.
  - Valida `status_code` antes de parsear respuesta.
- **Errores comunes:** quedarse colgado sin timeout, asumir JSON cuando llega HTML o texto.

### `beautifulsoup4` (`bs4`)
- **Para que sirve:** parsear HTML y extraer informacion web.
- **Donde se usa en E.D.A.:** `web_search.py`, `web_solver.py`.
- **Implementacion recomendada:**
  - Parsea con parser definido (`"html.parser"` o `lxml` si esta instalado).
  - Limpia texto (`get_text(" ", strip=True)`).
  - Limita cantidad de contenido para evitar respuestas enormes.
- **Errores comunes:** selectores fragiles que dejan de funcionar cuando cambia una pagina.

### `ollama`
- **Para que sirve:** interfaz con modelos LLM locales.
- **Donde se usa en E.D.A.:** proyecto configurado para `llama3.2:1b` via endpoint local.
- **Implementacion recomendada:**
  - Verificar disponibilidad del modelo al iniciar.
  - Usar fallback cuando Ollama no esta activo.
  - Guardar prompts compactos (historial resumido).
- **Errores comunes:** no controlar cuando el servicio local no responde.

### `pyttsx3`
- **Para que sirve:** texto a voz offline.
- **Donde se usa en E.D.A.:** `src/eda/tts.py`.
- **Implementacion recomendada:**
  - Inicializa motor una sola vez.
  - Selecciona voz en espanol si existe.
  - Evita bloquear hilo principal de GUI.
- **Errores comunes:** voces no instaladas o bloqueo del hilo UI al hablar.

### `SpeechRecognition`
- **Para que sirve:** voz a texto usando microfono y motores STT.
- **Donde se usa en E.D.A.:** `src/eda/stt.py`.
- **Implementacion recomendada:**
  - Calibra ruido ambiente.
  - Usa timeouts claros de escucha.
  - Maneja casos de audio vacio o no entendido.
- **Errores comunes:** excepciones por microfono ocupado o sin permisos.

### `pyaudio` (Windows)
- **Para que sirve:** acceso al microfono para STT.
- **Donde se usa en E.D.A.:** dependencia de voz.
- **Implementacion recomendada:**
  - Instalar usando ruedas compatibles con version de Python.
  - Probar microfono con script minimo antes de usar GUI.
- **Errores comunes:** fallos de instalacion binaria.

### `pyautogui`
- **Para que sirve:** automatizar mouse/teclado y acciones visuales.
- **Donde se usa en E.D.A.:** `mouse_keyboard.py` y acciones relacionadas.
- **Implementacion recomendada:**
  - Activa pausa corta entre acciones.
  - Usa coordenadas solo cuando sea necesario.
  - Agrega confirmacion para acciones sensibles.
- **Errores comunes:** automatizacion inestable por cambios de resolucion o ventanas.

### `pygetwindow`
- **Para que sirve:** detectar/manipular ventanas abiertas.
- **Donde se usa en E.D.A.:** `actions.py`.
- **Implementacion recomendada:**
  - Busca por coincidencia parcial de titulo.
  - Verifica si la ventana existe antes de operar.
- **Errores comunes:** titulos de ventana cambian segun idioma/version.

### `psutil`
- **Para que sirve:** metricas y procesos del sistema.
- **Donde se usa en E.D.A.:** optimizacion y monitoreo.
- **Implementacion recomendada:**
  - No hagas loops agresivos de lectura.
  - Captura excepciones de permisos al consultar procesos.
- **Errores comunes:** asumir acceso total a procesos protegidos.

### `comtypes` + `pycaw` (Windows)
- **Para que sirve:** `pycaw` controla el volumen maestro por la API de audio
  de Windows; **`comtypes`** es dependencia necesaria para que `pycaw` funcione
  (esta en `requirements.txt` y el `health_check.py` marca `windows:audio_stack`).
- **Donde se usa en E.D.A.:** `actions.py` (volumen; fallback a teclas
  multimedia si COM falla).
- **Implementacion recomendada:**
  - Validar rangos de volumen.
  - Fallback cuando COM/audio falle.
- **Errores comunes:** problemas de backend de audio en sesiones remotas;
  falta de `comtypes` con error al importar `pycaw`.

### `screen-brightness-control`
- **Para que sirve:** control de brillo.
- **Donde se usa en E.D.A.:** `actions.py` (brillo).
- **Implementacion recomendada:**
  - Clampear valores 0-100.
  - Mensaje de error claro si el monitor no soporta ajuste por software.
- **Errores comunes:** algunos monitores externos no exponen control.

### `bleak`
- **Para que sirve:** Bluetooth (escaneo/conexion) multiplataforma.
- **Donde se usa en E.D.A.:** `bluetooth_manager.py`.
- **Implementacion recomendada:**
  - Manejar bien `asyncio` (event loop controlado).
  - Timeouts en escaneo.
  - Guardar favoritos/dispositivos en memoria.
- **Errores comunes:** permisos o adaptador Bluetooth apagado.

### `pyperclip`
- **Para que sirve:** leer/escribir portapapeles.
- **Donde se usa en E.D.A.:** utilidades de acciones en `src/eda/actions.py`.
- **Implementacion recomendada:**
  - Validar contenido vacio.
  - Sanitizar texto antes de uso automatico.
- **Errores comunes:** conflicto con apps que bloquean clipboard.

### `googlesearch-python`
- **Para que sirve:** obtener resultados de Google (fallback).
- **Donde se usa en E.D.A.:** flujo de busqueda web.
- **Implementacion recomendada:**
  - Limitar numero de resultados.
  - Usar como fallback, no como unica fuente.
- **Errores comunes:** cambios anti-bot y bloqueos temporales.

### `duckduckgo-search`
- **Para que sirve:** busquedas web sin depender solo de Google.
- **Donde se usa en E.D.A.:** `web_search.py`.
- **Implementacion recomendada:**
  - Mezclar fuentes y reordenar por relevancia.
  - Cachear consultas frecuentes.
- **Errores comunes:** respuestas vacias por rate-limit.

### `lxml`
- **Para que sirve:** parser HTML/XML rapido y robusto.
- **Donde se usa en E.D.A.:** soporte para parsing en scraping.
- **Implementacion recomendada:**
  - Usar cuando busques mayor velocidad que parser basico.
  - Mantener fallback a parser estandar.
- **Errores comunes:** incompatibilidades binarias en entornos mal configurados.

### `Pillow`
- **Para que sirve:** imagenes (capturas/procesamiento simple).
- **Donde se usa en E.D.A.:** utilidades graficas y posibles capturas.
- **Implementacion recomendada:**
  - Abrir archivos con contexto y validar formato.
  - Evitar procesado pesado en hilo UI.
- **Errores comunes:** consumo de memoria con imagenes grandes.

### `schedule`
- **Para que sirve:** tareas programadas simples.
- **Donde se usa en E.D.A.:** `scheduler.py`.
- **Implementacion recomendada:**
  - Ejecutar scheduler en hilo dedicado.
  - Controlar parada limpia al cerrar app.
- **Errores comunes:** jobs duplicados o loops sin `sleep`.

### `pipwin` (Windows)
- **Para que sirve:** ayudar a instalar paquetes binarios complicados.
- **Donde se usa en E.D.A.:** soporte de instalacion en Windows.
- **Implementacion recomendada:**
  - Usar solo cuando `pip` normal falla.
  - Documentar claramente cuando es necesario.
- **Errores comunes:** usarlo para todo en lugar de dependencias normales.

## 3) Librerias de la libreria estandar (tambien importantes)

- `tkinter`: GUI principal (`src/ui_main.py`) y fallback visual.
- `threading`: tareas en paralelo sin bloquear UI.
- `asyncio`: operaciones Bluetooth.
- `subprocess`: comandos del sistema.
- `json` y `pathlib`: persistencia y rutas robustas.
- `logging`: trazabilidad y diagnostico.

## 4) Mejores practicas globales de implementacion

1. **No bloquear la GUI**
   - Todo lo pesado (red, scraping, IA, audio) fuera del hilo principal.

2. **Siempre con timeout**
   - Red, escaneo, acciones largas.

3. **Manejo de errores uniforme**
   - Nunca silenciar excepciones.
   - Log tecnico + mensaje amigable.

4. **Configuracion centralizada**
   - Parametros en `config.py` (modelo, timeouts, rutas, limites).

5. **Persistencia segura**
   - Guardar JSON de forma atomica (ya implementado en `utils.py`).

6. **Compatibilidad gradual**
   - Mantener formato viejo y nuevo cuando migres memoria/datos.

## 5) Plantilla rapida para integrar una libreria nueva

1. Agregar dependencia en `requirements.txt`.
2. Crear modulo dedicado (ejemplo: `mi_modulo.py`).
3. Encapsular uso con una clase simple.
4. Manejar errores internos y devolver dict estandar (`status`, `message`, `data`).
5. Conectar el modulo desde `src/ui_main.py` o `src/eda/actions.py`.
6. Documentar en `README.md` y en esta guia.

## 6) Prioridad recomendada para mejorar el proyecto

- Primero: `requests`, `voice`, `memory`, `actions`.
- Despues: `web_solver`/scraping.
- Al final: automatizaciones avanzadas y mejoras incrementales de flujos existentes.

---

Si eres novato, no intentes optimizar todas las librerias en una sola semana.  
Haz una mejora pequena por modulo, pruebala, y recien ahi pasa al siguiente paso.
