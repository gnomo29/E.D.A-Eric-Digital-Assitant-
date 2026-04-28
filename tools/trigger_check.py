#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from eda.triggers import TriggerStore


def main() -> int:
    store = TriggerStore()
    rows = store.list_triggers(active_only=False)
    sample = ["ironman", "ir al gym", "reproduce vegeta777"]
    matches = {}
    for s in sample:
        m = store.match(s)
        matches[s] = m.get("trigger", {}).get("id") if isinstance(m, dict) and m.get("trigger") else None
    report = {
        "total_triggers": len(rows),
        "active_triggers": len([r for r in rows if r.get("active")]),
        "sample_matches": matches,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
