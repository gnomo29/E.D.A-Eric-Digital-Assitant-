#!/usr/bin/env python3
"""Diagnóstico Spotify: token, dispositivos, playlists; reproducción solo en dry-run."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from eda.utils import load_env_dotfile

load_env_dotfile()


def main() -> int:
    from eda.spotify_web import describe_integration_status, get_spotify_client, is_web_api_configured

    print("Estado:", describe_integration_status())
    if not is_web_api_configured():
        print("Configurá EDA_SPOTIFY_CLIENT_ID y PKCE o secret (ver .env.example).")
        return 1

    sp = get_spotify_client()
    if not sp:
        print("No se pudo crear el cliente; revisá credenciales y spotipy.")
        return 2

    u = sp.current_user() or {}
    print("Usuario API:", (u.get("display_name") or u.get("id") or "?"))
    try:
        devs = (sp.devices() or {}).get("devices") or []
    except Exception as exc:
        print("devices():", exc)
        devs = []
    print(f"Dispositivos ({len(devs)}):")
    for d in devs[:20]:
        name = d.get("name")
        did = d.get("id")
        active = d.get("is_active")
        print(f"  - {name!r}  id={did}  activo={active}")

    try:
        pl = (sp.current_user_playlists(limit=20) or {}).get("items") or []
    except Exception as exc:
        print("playlists():", exc)
        pl = []
    print(f"Playlists (muestra {len(pl)}):")
    for p in pl:
        print("  -", p.get("name"), "=>", p.get("uri"))

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--play-dry-run",
        action="store_true",
        help="Muestra el payload de start_playback de prueba sin llamar a la API de reproducción.",
    )
    args = ap.parse_args()
    if args.play_dry_run:
        print("Dry-run: se mostraría start_playback(uris=['spotify:track:...primer resultado...']).")
        try:
            res = sp.search(q="test", type="track", limit=1)
            items = ((res or {}).get("tracks") or {}).get("items") or []
            if items:
                uri = items[0].get("uri")
                print("Ejemplo de URI:", uri)
        except Exception as exc:
            print("Búsqueda de prueba falló:", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
