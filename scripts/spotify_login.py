#!/usr/bin/env python3
"""
Primera autenticación Spotify Web API: abre el navegador y guarda el token en .cache/

Uso (desde la raíz del repo, con el venv activado):
  python scripts/spotify_login.py

Requiere EDA_SPOTIFY_CLIENT_ID y redirect URI registrada en el dashboard de Spotify.
Ver .env.example
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eda.utils import load_env_dotfile

load_env_dotfile()


def main() -> int:
    from eda.spotify_web import describe_integration_status, is_web_api_configured, warmup_oauth

    print("Estado:", describe_integration_status())
    if not is_web_api_configured():
        print(
            "Configure EDA_SPOTIFY_CLIENT_ID (y EDA_SPOTIFY_CLIENT_SECRET o EDA_SPOTIFY_USE_PKCE=1). "
            "Copie .env.example → .env o exporte variables."
        )
        return 1
    ok = warmup_oauth()
    if ok:
        print("Listo. Token guardado bajo .cache/ (no lo suba a Git).")
        return 0
    print("Falló el login; revise la consola y que el redirect URI coincida con el dashboard.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
