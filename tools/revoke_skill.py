"""CLI para revocar/reinstaurar skills firmadas."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from eda.utils.revocation import list_revoked, revoke_skill, unrevoke_skill


def main() -> None:
    parser = argparse.ArgumentParser(description="Gestiona revocaciones de skills")
    parser.add_argument("action", choices=["revoke", "unrevoke", "list"], help="Operación")
    parser.add_argument("skill", nargs="?", default="", help="Archivo skill (ej. example_skill.py)")
    parser.add_argument("--reason", default="", help="Motivo de revocación")
    args = parser.parse_args()

    if args.action == "list":
        revoked = list_revoked()
        if not revoked:
            print("No hay skills revocadas.")
            return
        print("Skills revocadas:")
        for skill_name, meta in revoked.items():
            print(f"- {skill_name}: {meta}")
        return

    if not args.skill:
        raise SystemExit("Debes indicar una skill para revoke/unrevoke.")

    if args.action == "revoke":
        ok = revoke_skill(args.skill, reason=args.reason)
        print("Revocación aplicada." if ok else "No pude revocar skill.")
        return

    ok = unrevoke_skill(args.skill)
    print("Skill reinstaurada (unrevoke)." if ok else "No pude reinstaurar skill.")


if __name__ == "__main__":
    main()

