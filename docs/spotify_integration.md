# Integración Spotify (reproducción y biblioteca)

## Scopes OAuth

Requiere consentimiento con estos permisos (definidos en `src/eda/spotify_web.py`):

| Scope | Uso |
|--------|-----|
| `user-read-playback-state` | Leer dispositivo y estado |
| `user-modify-playback-state` | Iniciar / transferir / shuffle / repeat |
| `user-read-currently-playing` | Coherencia con cola y dispositivo |
| `user-library-read` | “Tus me gusta” y álbumes guardados |
| `playlist-read-private` | Listas del usuario no públicas |
| `user-read-private` | Identificar titular de playlists |

Si amplías scopes respecto a una sesión antigua, borrá `.cache/spotify_token_cache.json` y volvé a ejecutar `python scripts/spotify_login.py`.

## Claves y Redirect URI

1. Creá una app en [Spotify for Developers](https://developer.spotify.com/dashboard/).
2. Añadí **Redirect URI** exacta: `http://127.0.0.1:8888/callback` (HTTP local; el dashboard acepta `http` en loopback).
3. En `.env` (ver `.env.example`):
   - `EDA_SPOTIFY_CLIENT_ID=...`
   - `EDA_SPOTIFY_USE_PKCE=1` (recomendado en repositorios; sin client secret en el repo) **o** `EDA_SPOTIFY_CLIENT_SECRET=...` (app “confidential”).

## Primer login

```text
python scripts/spotify_login.py
```

Se abre el navegador, aceptás permisos y el token se guarda en **`.cache/spotify_token_cache.json`**. No subas esa carpeta a Git.

## Comportamiento del asistente

- Módulo canónico del conector: `src/eda/connectors/spotify.py`.
- **Umbrales** (configurables por entorno): `EDA_SPOTIFY_CONF_AUTO`, `EDA_SPOTIFY_CONF_AMBIG_LOW` (ver `src/eda/config.py`).
- **Historial de acciones**: JSONL en `logs/spotify_actions.jsonl` (sin tokens en claro).
- **Transferencia de dispositivo**: si `EDA_SPOTIFY_TRANSFER_REQUIRES_CONFIRM=1`, se pide **Sí/No** antes de mover la reproducción.
- **Aclaración**: si hay varios candidatos de álbum o lista, el chat muestra hasta **3 opciones**; respondé `1`, `2` o `3`.

## Ejemplos en español

- «Reproduce el álbum Abbey Road de The Beatles»
- «Pon mis me gusta en reproducción, en modo shuffle»
- «Toca la playlist Entreno mañanas»
- «Reproduce la canción Shape of You»
- «Pon algo similar a Radiohead»
- «Pasa la reproducción al altavoz de la sala»
- «Reproduce el último álbum de Dua Lipa»

## Triggers con Spotify

- Crear por chat:
  - `crear disparador: cuando diga "ironman" reproduce acdc`
- Flujo:
  - EDA pide confirmación.
  - Si confirmás, guarda el trigger en `data/memory/long_term.db`.
  - Luego, al decir `ironman`, ejecuta reproducción Spotify.

## Herramienta de diagnóstico

```text
python tools/spotify_check.py
```

Lista estado del token, dispositivos y playlists; **dry-run** de reproducción sin ejecutar salvo confirmación explícita.
