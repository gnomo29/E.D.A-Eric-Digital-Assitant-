# Docs Changelog

## 2026-04-28

Se consolidó el enrutamiento inteligente del asistente para priorizar música y conversación sobre ejecución directa de acciones. El `CommandOrchestrator` ahora decide primero rutas de Spotify (incluyendo frases ambiguas), luego clasificación conversacional hacia LLM, y usa `ActionAgent` solo cuando realmente hay intención operativa. Además, se añadieron trazas explícitas de ruta con score de confianza para facilitar depuración en producción.

También se integró la UI Obsidian (`src/ui_main.py`) al orquestador unificado, evitando respuestas genéricas de “acción directa” para preguntas normales. Se incorporaron mejoras de UX visual (padding de burbujas de usuario), test unitarios de matriz de enrutamiento y control configurable de liberación de memoria de Ollama bajo presión de RAM.
