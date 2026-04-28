"""Firma individual de skills sin regenerar llaves."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from eda.utils.security import sign_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Firma una skill individual y actualiza signatures.json")
    parser.add_argument("skill_file", help="Nombre del archivo .py dentro de skills/, o ruta absoluta")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    skills_dir = root / "skills"
    keys_dir = root / "config" / "keys"
    private_key = keys_dir / "skills_private.pem"
    signatures_path = skills_dir / "signatures.json"

    if not private_key.exists():
        raise SystemExit("No existe llave privada. Ejecuta primero: python tools/sign_skill.py")

    target = Path(args.skill_file)
    if not target.is_absolute():
        target = skills_dir / target
    if not target.exists() or target.suffix.lower() != ".py":
        raise SystemExit(f"Skill inválida: {target}")

    payload = {}
    if signatures_path.exists():
        try:
            payload = json.loads(signatures_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    files = payload.get("files")
    if not isinstance(files, dict):
        files = {}

    files[target.name] = sign_file(target, private_key)
    manifest = skills_dir / "manifest.json"
    if manifest.exists():
        files["manifest.json"] = sign_file(manifest, private_key)

    signatures_path.write_text(json.dumps({"files": files}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Skill firmada: {target.name}")
    print(f"Signatures actualizadas: {signatures_path}")


if __name__ == "__main__":
    main()

