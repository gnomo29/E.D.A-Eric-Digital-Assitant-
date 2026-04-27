"""Genera llaves locales y firma skills/*.py + manifest.json."""

from __future__ import annotations

import json
from pathlib import Path

from eda.utils.security import generate_skill_keypair, sign_file


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    skills_dir = root / "skills"
    keys_dir = root / "config" / "keys"
    private_key = keys_dir / "skills_private.pem"
    public_key = keys_dir / "skills_public.pem"
    signatures_path = skills_dir / "signatures.json"

    if not private_key.exists() or not public_key.exists():
        generate_skill_keypair(private_key, public_key)

    signatures: dict[str, str] = {}
    targets = [skills_dir / "manifest.json"] + sorted(skills_dir.glob("*.py"))
    for target in targets:
        if not target.exists():
            continue
        signatures[target.name] = sign_file(target, private_key)

    signatures_path.write_text(json.dumps({"files": signatures}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Firmas actualizadas: {signatures_path}")
    print(f"Llave pública: {public_key}")


if __name__ == "__main__":
    main()

