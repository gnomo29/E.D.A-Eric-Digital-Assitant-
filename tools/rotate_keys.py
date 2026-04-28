"""Rotación segura de llaves de firma de skills."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from eda.utils.security import generate_skill_keypair, sign_file, verify_file_signature


def _backup_file(path: Path, backup_dir: Path) -> None:
    if not path.exists():
        return
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_dir / path.name)


def rollback_rotation(root: Path) -> dict[str, str]:
    keys_dir = root / "config" / "keys"
    skills_dir = root / "skills"
    private_key = keys_dir / "skills_private.pem"
    public_key = keys_dir / "skills_public.pem"
    signatures_path = skills_dir / "signatures.json"
    private_old = keys_dir / "skills_private.old.pem"
    public_old = keys_dir / "skills_public.old.pem"
    signatures_old = skills_dir / "signatures.old.json"

    if private_old.exists():
        if private_key.exists():
            private_key.unlink()
        private_old.replace(private_key)
    if public_old.exists():
        if public_key.exists():
            public_key.unlink()
        public_old.replace(public_key)
    if signatures_old.exists():
        if signatures_path.exists():
            signatures_path.unlink()
        signatures_old.replace(signatures_path)
    return {"status": "ok", "message": "Rollback aplicado usando *.old"}


def run_rotation(root: Path, *, dry_run: bool = False, force: bool = False) -> dict[str, str]:
    keys_dir = root / "config" / "keys"
    skills_dir = root / "skills"
    private_key = keys_dir / "skills_private.pem"
    public_key = keys_dir / "skills_public.pem"
    private_new = keys_dir / "skills_private_new.pem"
    public_new = keys_dir / "skills_public_new.pem"
    private_old = keys_dir / "skills_private.old.pem"
    public_old = keys_dir / "skills_public.old.pem"
    signatures_path = skills_dir / "signatures.json"
    signatures_temp = skills_dir / "signatures.json.temp"
    signatures_old = skills_dir / "signatures.old.json"

    if dry_run:
        return {"status": "ok", "message": "Dry-run: no se escribieron cambios."}

    if (private_new.exists() or public_new.exists() or signatures_temp.exists()) and not force:
        return {"status": "error", "message": "Existen archivos *_new o .temp. Usa --force o limpia estado previo."}

    keys_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)
    backup_dir = root / "data" / "backups" / f"keys_rotation_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    _backup_file(private_key, backup_dir)
    _backup_file(public_key, backup_dir)
    _backup_file(signatures_path, backup_dir)

    if force:
        for p in [private_new, public_new, signatures_temp]:
            if p.exists():
                p.unlink()

    generate_skill_keypair(private_new, public_new)

    signatures: dict[str, str] = {}
    targets = [skills_dir / "manifest.json"] + sorted(skills_dir.glob("*.py"))
    for target in targets:
        if not target.exists():
            continue
        signatures[target.name] = sign_file(target, private_new)
    signatures_temp.write_text(json.dumps({"files": signatures}, indent=2, ensure_ascii=False), encoding="utf-8")

    for target in targets:
        if not target.exists():
            continue
        sig = signatures.get(target.name, "")
        if not sig or not verify_file_signature(target, sig, public_new):
            return {"status": "error", "message": f"Validación fallida para {target.name}. Ejecuta --rollback si aplica."}

    if private_old.exists():
        if force:
            private_old.unlink()
        else:
            return {"status": "error", "message": "Existe skills_private.old.pem; usa --force o rollback manual."}
    if public_old.exists():
        if force:
            public_old.unlink()
        else:
            return {"status": "error", "message": "Existe skills_public.old.pem; usa --force o rollback manual."}
    if signatures_old.exists():
        if force:
            signatures_old.unlink()
        else:
            return {"status": "error", "message": "Existe signatures.old.json; usa --force o rollback manual."}

    try:
        if private_key.exists():
            private_key.replace(private_old)
        if public_key.exists():
            public_key.replace(public_old)
        private_new.replace(private_key)
        public_new.replace(public_key)

        if signatures_path.exists():
            signatures_path.replace(signatures_old)
        signatures_temp.replace(signatures_path)
    except Exception as exc:
        rollback_rotation(root)
        return {"status": "error", "message": f"Fallo en promoción atómica; rollback aplicado: {exc}"}

    return {"status": "ok", "message": "Rotación completada. Llaves previas respaldadas y movidas a *.old"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Rota llaves de firma de skills con validación y rollback")
    parser.add_argument("--dry-run", action="store_true", help="Simula sin escribir cambios")
    parser.add_argument("--force", action="store_true", help="Sobrescribe estado temporal previo")
    parser.add_argument("--rollback", action="store_true", help="Restaura llaves/firmas desde *.old")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    if args.rollback:
        result = rollback_rotation(root)
    else:
        result = run_rotation(root, dry_run=args.dry_run, force=args.force)
    print(result["message"])
    if result.get("status") != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

