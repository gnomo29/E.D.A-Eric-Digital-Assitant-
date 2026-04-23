# Guia Novato: que tocar en cada archivo

Esta guia te dice, en palabras simples, que hace cada modulo y que debes hacer ahi cuando quieras mejorar E.D.A.

## Regla de oro

- Cambia una sola cosa por vez.
- Prueba despues de cada cambio con `python main.py --cli`.
- Si funciona en CLI, prueba en GUI con `python main.py`.
- Evita editar `venv312/` (son librerias externas).

## Flujo mental del proyecto

1. El usuario escribe o habla.
2. `gui.py` recibe el texto.
3. `nlp_utils.py` detecta intencion.
4. Se ejecuta `actions.py` (si es comando de sistema) o `core.py` (si es pregunta IA).
5. `memory.py` guarda lo ocurrido.

## Archivo por archivo (que hace y que hacer)

### `main.py`
- **Que hace:** arranca la app en modo GUI o CLI.
- **Que hacer aqui:** solo cosas de inicio (argumentos, modo debug, logs iniciales).
- **Evita:** meter logica de comandos aqui.

### `gui.py`
- **Que hace:** interfaz de usuario y flujo principal de mensajes.
- **Que hacer aqui:** botones, estado visual, conexion entre UI y modulos.
- **Evita:** logica pesada dentro de callbacks; mejor delegar a otros modulos.

### `core.py`
- **Que hace:** crea prompts y consulta IA (Ollama) con fallback.
- **Que hacer aqui:** mejorar calidad de respuestas, prompt y reglas de fallback.
- **Evita:** automatizacion del sistema (eso va en `actions.py`).

### `actions.py`
- **Que hace:** abre/cierra apps y ejecuta acciones del sistema.
- **Que hacer aqui:** agregar comandos nuevos de Windows paso a paso.
- **Evita:** mezclar manejo de memoria o UI.

### `memory.py`
- **Que hace:** guarda memoria persistente en JSON.
- **Que hacer aqui:** mejoras de historial, validacion, limites y recuperacion.
- **Tip:** usa `append_chat_message()` para formato `role/content/timestamp`.

### `config.py`
- **Que hace:** constantes globales (modelo, rutas, ajustes).
- **Que hacer aqui:** centralizar parametros, no valores sueltos por el codigo.

### `voice.py`
- **Que hace:** texto a voz y voz a texto.
- **Que hacer aqui:** mejorar idioma, calidad de escucha, mensajes de error.
- **Evita:** logica de negocio.

### `nlp_utils.py`
- **Que hace:** interpreta intenciones del usuario.
- **Que hacer aqui:** nuevos patrones de intencion y entidades.

### `web_search.py` y `web_solver.py`
- **Que hacen:** busqueda y resolucion tecnica en web.
- **Que hacer aqui:** timeouts, reintentos, filtros de calidad y resumenes.

### `optimizer.py`
- **Que hace:** rutinas de optimizacion/mantenimiento del sistema.
- **Que hacer aqui:** agregar tareas seguras con confirmacion.

### `scheduler.py`
- **Que hace:** tareas programadas.
- **Que hacer aqui:** recordatorios simples y validaciones de fecha/hora.

### `bluetooth_manager.py`
- **Que hace:** escaneo y acciones Bluetooth.
- **Que hacer aqui:** conectar/desconectar con manejo robusto de errores.

### `system_info.py`
- **Que hace:** metricas del sistema (CPU, RAM, etc.).
- **Que hacer aqui:** agregar metricas utiles y normalizar formato.

### `file_manager.py`, `clipboard.py`, `mouse_keyboard.py`
- **Que hacen:** utilidades de archivos, portapapeles y entrada.
- **Que hacer aqui:** funciones pequenas, claras y con permisos seguros.

### `logger.py`
- **Que hace:** configuracion de logs.
- **Que hacer aqui:** formato de logs y niveles (`INFO`, `ERROR`).

### `utils.py`
- **Que hace:** funciones de apoyo reutilizables.
- **Que hacer aqui:** helpers puros y seguros (JSON, rutas, comandos protegidos).

### `evolution.py`
- **Que hace:** autoevolucion de codigo.
- **Que hacer aqui:** mucha cautela; primero entender, luego tocar.
- **Recomendacion:** no modificar este modulo hasta dominar el resto.

## Tu plan de trabajo semanal (novato)

### Semana 1
- Leer `main.py`, `gui.py`, `memory.py`.
- Ejecutar en CLI y GUI.
- Cambiar solo textos de respuesta.

### Semana 2
- Agregar 1 comando nuevo en `actions.py`.
- Agregar su deteccion en `nlp_utils.py`.
- Probar 5 casos (normal + errores).

### Semana 3
- Mejorar memoria (`memory.py`) y logs (`logger.py`).
- Agregar validaciones y mensajes claros al usuario.

### Semana 4
- Mejorar calidad de IA en `core.py`.
- Ajustar web fallback en `web_solver.py`.

## Checklist antes de guardar cambios

- El proyecto inicia con `python main.py --cli`.
- El comando nuevo funciona y no rompe los existentes.
- `memory/memoria.json` se sigue guardando bien.
- No editaste nada dentro de `venv312/`.

## Primera tarea recomendada (muy segura)

1. Crear un comando nuevo simple en `actions.py` (ejemplo: abrir calculadora).
2. Detectarlo en `nlp_utils.py`.
3. Probarlo desde CLI.
4. Documentarlo en `README.md`.

Si haces este ciclo 3 veces, ya estaras programando el proyecto con confianza.
