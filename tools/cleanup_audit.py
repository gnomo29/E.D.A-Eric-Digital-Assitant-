#!/usr/bin/env python3
from __future__ import annotations

import ast
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv312",
    "__pycache__",
    "data",
    "logs",
    "temp",
    "backups",
}


def iter_files() -> list[Path]:
    out: list[Path] = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        out.append(p)
    return out


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def build_duplicate_groups(files: list[Path]) -> list[list[str]]:
    by_hash: dict[str, list[str]] = {}
    for p in files:
        if p.suffix.lower() not in {".py", ".md", ".json", ".yml", ".yaml", ".sh", ".bat", ".txt", ".toml"}:
            continue
        by_hash.setdefault(sha256(p), []).append(str(p.relative_to(ROOT)))
    return [v for v in by_hash.values() if len(v) > 1]


def parse_imports(py_path: Path) -> set[str]:
    mods: set[str] = set()
    try:
        tree = ast.parse(py_path.read_text(encoding="utf-8"))
    except Exception:
        return mods
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module)
    return mods


def module_name(path: Path) -> str:
    rel = path.relative_to(ROOT)
    if rel.parts[0] == "src":
        rel = Path(*rel.parts[1:])
    return ".".join(rel.with_suffix("").parts)


def find_unused_python(files: list[Path]) -> list[str]:
    py_files = [p for p in files if p.suffix == ".py"]
    all_imports: set[str] = set()
    for p in py_files:
        all_imports |= parse_imports(p)
    unused: list[str] = []
    for p in py_files:
        rel = p.relative_to(ROOT)
        if rel.parts and rel.parts[0] in {"tests", "tools"}:
            continue
        mod = module_name(p)
        if mod.endswith("__init__"):
            continue
        if not any(i == mod or i.startswith(mod + ".") for i in all_imports):
            unused.append(str(rel))
    return sorted(unused)


def write_import_map_csv(path: Path) -> None:
    rows = [
        ("old_route", "new_route"),
        ("eda.actions", "src.eda.actions"),
        ("eda.core", "src.eda.core"),
        ("eda.memory", "src.eda.memory"),
        ("eda.orchestrator", "src.eda.orchestrator"),
        ("eda.connectors.spotify", "src.eda.connectors.spotify"),
        ("old_launchers/*", "legacy/old_launchers/*"),
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for r in rows:
            w.writerow(r)


def main() -> int:
    files = iter_files()
    report = {
        "duplicate_groups": build_duplicate_groups(files),
        "unused_python_candidates": find_unused_python(files)[:120],
        "canonical_modules": {
            "spotify": "src/eda/connectors/spotify.py",
            "youtube": "src/eda/connectors/youtube.py",
            "orchestrator": "src/eda/orchestrator.py",
            "ui": "src/ui_main.py",
        },
    }
    out = ROOT / "logs" / "cleanup_audit_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_import_map_csv(ROOT / "logs" / "import_map.csv")
    print(json.dumps({"report": str(out.relative_to(ROOT)), "import_map_csv": "logs/import_map.csv"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
