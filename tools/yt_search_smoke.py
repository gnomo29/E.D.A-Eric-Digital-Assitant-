from __future__ import annotations

import argparse
import json

from eda.connectors.youtube import channel_lookup_candidates, classify_youtube_intent, search_youtube_candidates


def main() -> int:
    p = argparse.ArgumentParser(description="Smoke test de búsqueda YouTube (sin abrir navegador).")
    p.add_argument("query", nargs="?", default="vegeta777", help="Consulta de prueba")
    args = p.parse_args()

    q = str(args.query or "").strip()
    kind = classify_youtube_intent(f"reproduce {q}")
    if kind == "channel_lookup":
        rows = channel_lookup_candidates(q)
    else:
        rows = search_youtube_candidates(q)
    print(json.dumps({"query": q, "intent_kind": kind, "candidates": rows[:5]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
